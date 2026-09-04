"""
Django Channels WebSocket consumer — thin relay between Twilio Media Streams
and the Deepgram Voice Agent API.

The Voice Agent API replaces the old DIY pipeline (Deepgram STT → OpenAI →
Deepgram Aura TTS) with a single managed WebSocket that handles listening,
thinking, speaking, turn-taking, and barge-in natively. This consumer only:

    Twilio (mulaw 8kHz, base64 JSON) ←→ Deepgram Voice Agent (raw bytes)

plus business logic on function calls: `place_order` saves the order and
sends the SMS; `end_conversation` (or a closed agent socket) hangs up the
Twilio call via REST.

Pattern follows Deepgram's reference implementation:
https://github.com/deepgram-devs/deepgram-voice-agent-inbound-telephony
"""

import asyncio
import base64
import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings
from deepgram import AsyncDeepgramClient
from deepgram.agent.v1 import (
    AgentV1AgentAudioDone,
    AgentV1AgentStartedSpeaking,
    AgentV1ConversationText,
    AgentV1Error,
    AgentV1FunctionCallRequest,
    AgentV1SendFunctionCallResponse,
    AgentV1SettingsApplied,
    AgentV1UserStartedSpeaking,
    AgentV1Warning,
)
from deepgram.agent.v1.socket_client import V1SocketClientResponse
from deepgram.core.pydantic_utilities import parse_obj_as

from .agent import build_agent_settings, save_order_from_agent
from .clover import send_order_to_clover
from .notify import get_twilio_client, send_order_sms
from .transfer import build_transfer_twiml, transfer_enabled

logger = logging.getLogger(__name__)

SETTINGS_TIMEOUT = 5.0   # Seconds to wait for SettingsApplied before giving up
HANGUP_DELAY = 3.0       # Seconds to let the agent's final audio finish before hangup
POST_ORDER_QUIET_DELAY = 3.0  # End the call this long after the agent's last completed
                              # utterance following place_order. Re-armed per utterance and
                              # cancelled when speech starts, so it can never fire mid-speech.
                              # No fixed post-place_order hard timer exists — one (16s) could
                              # land while a long goodbye is still streaming.


class CallConsumer(AsyncWebsocketConsumer):
    """
    Handles one phone call from start to finish.

    Lifecycle:
        connect (start agent socket + settings) → receive (Twilio audio loop)
        → listen loop (agent messages) → disconnect (cleanup + hangup)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.call_sid = ''
        self.caller_phone = ''
        self.stream_sid = ''
        self.dg_client = None        # AsyncDeepgramClient
        self.dg_ctx = None           # Async context manager from agent.v1.connect()
        self.dg_socket = None        # AsyncV1SocketClient
        self.listen_task = None      # Agent → Twilio message loop
        self._settings_applied = asyncio.Event()
        self._hangup_scheduled = False
        self._cleaned_up = False
        self._after_place_order = False
        self._quiet_hangup_task = None  # Pending post-order quiet hangup (re-armed per utterance)
        self._transferred = False       # Transfer succeeded: never REST-hangup, Twilio owns the call
        self._transfer_result_url = ''  # Absolute <Dial action> URL from the voice webhook
        self._media_forwarded = 0    # Audio packet counter for liveness logging
        self._pre_stream_buffer = []  # Agent audio before Twilio 'start' (flushed once stream_sid known)

    async def connect(self):
        """Accept Twilio's WebSocket and bring up the Deepgram agent socket."""
        await self.accept()
        logger.info('Call WebSocket connected')

        try:
            # Open the Deepgram Voice Agent socket (outlives any function scope)
            self.dg_client = AsyncDeepgramClient(api_key=settings.DEEPGRAM_API_KEY)
            self.dg_ctx = self.dg_client.agent.v1.connect()
            self.dg_socket = await self.dg_ctx.__aenter__()

            # Configure the agent (models, prompt, functions, greeting, audio).
            # build_agent_settings queries the ORM (get_menu_text) — must run
            # in a sync thread, not the async event loop.
            settings_payload = await sync_to_async(
                build_agent_settings, thread_sensitive=False
            )()
            await self.dg_socket.send_settings(settings_payload)
        except Exception as e:
            logger.error(f'Voice agent startup failed: {e}')
            await self.close()
            return

        # Start reading agent messages; handles function calls + audio out
        self.listen_task = asyncio.create_task(self._listen_loop())

        # Wait for settings to be applied — audio sent before that is dropped
        try:
            await asyncio.wait_for(self._settings_applied.wait(), timeout=SETTINGS_TIMEOUT)
            logger.info('Deepgram Voice Agent ready (settings applied)')
        except asyncio.TimeoutError:
            logger.error('Settings never applied within %.0fs — closing call',
                         SETTINGS_TIMEOUT)
            await self._hangup_now()

    async def disconnect(self, close_code):
        """Call ended — tear down the agent socket and tasks."""
        logger.info(f'Call WebSocket disconnected (code: {close_code})')
        await self._cleanup()

    async def receive(self, text_data=None, bytes_data=None):
        """Handle Twilio Media Stream events: start, media, stop."""
        if not text_data:
            return
        msg = json.loads(text_data)
        event = msg.get('event', '')

        if event == 'start':
            start_data = msg.get('start', {})
            self.call_sid = start_data.get('callSid', '')
            self.stream_sid = msg.get('streamSid', '')
            custom_params = start_data.get('customParameters', {})
            self.caller_phone = custom_params.get('caller_phone', '')
            self._transfer_result_url = custom_params.get('transfer_result_url', '')
            logger.info(f'Stream started — call: {self.call_sid}, from: {self.caller_phone}')
            # Flush any agent audio that arrived before the stream started
            if self._pre_stream_buffer:
                logger.info(f'Flushing {len(self._pre_stream_buffer)} pre-stream audio chunks')
                for chunk in self._pre_stream_buffer:
                    await self._send_agent_audio(chunk)
                self._pre_stream_buffer.clear()

        elif event == 'media':
            audio_bytes = base64.b64decode(msg['media']['payload'])
            if self.dg_socket and self._settings_applied.is_set():
                try:
                    await self.dg_socket.send_media(audio_bytes)
                except Exception as e:
                    # Agent socket can close mid-transfer (Twilio 'stop' + our
                    # teardown race the last audio) — stop forwarding, don't crash.
                    logger.debug(f'Agent socket send failed: {e}')
                    return
                self._media_forwarded += 1
                if self._media_forwarded % 250 == 1:  # Log every ~5s (50 packets/s)
                    logger.info(f'🎙 Audio streaming: {self._media_forwarded} packets forwarded')
            else:
                # Agent not ready yet — Deepgram drops pre-settings audio anyway
                logger.debug('Dropping audio before settings applied')

        elif event == 'stop':
            logger.info('Stream stopped by Twilio (customer hung up)')
            await self._hangup_now()

    # ------------------------------------------------------------------
    # Deepgram → Twilio
    # ------------------------------------------------------------------

    async def _listen_loop(self):
        """
        Read agent messages until the socket closes.

        Iterates the raw websocket (not the SDK's start_listening, which
        raises on unknown message types) and parses each frame defensively.
        Socket close is the hangup signal for server-side end_conversation.
        """
        try:
            async for raw in self.dg_socket._websocket:
                if isinstance(raw, bytes):
                    await self._send_agent_audio(raw)
                else:
                    try:
                        message = parse_obj_as(V1SocketClientResponse, json.loads(raw))
                    except Exception:
                        logger.debug('Skipping unrecognized agent message')
                        continue
                    await self._handle_agent_message(message)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f'Agent listen loop error: {e}')
        finally:
            logger.info('Agent socket closed — finishing call')
            # Server-side end_conversation (or error) closed the socket:
            # hang up the Twilio call unless one is already scheduled.
            if not self._hangup_scheduled:
                await self._hangup_now()

    async def _handle_agent_message(self, message):
        if isinstance(message, AgentV1SettingsApplied):
            self._settings_applied.set()

        elif isinstance(message, AgentV1FunctionCallRequest):
            await self._handle_function_call(message)

        elif isinstance(message, AgentV1ConversationText):
            logger.info(f'{message.role.upper()}: {message.content}')

        elif isinstance(message, AgentV1UserStartedSpeaking):
            # Barge-in: customer started talking mid-agent-speech — flush
            # Twilio's playback buffer so the caller hears themselves clearly.
            if self.stream_sid:
                await self.send(text_data=json.dumps({
                    'event': 'clear',
                    'streamSid': self.stream_sid,
                }))

        elif isinstance(message, AgentV1AgentAudioDone):
            logger.debug('Agent audio finished')
            # After a successful place_order the call should end shortly after
            # the agent's closing speech. Each finished utterance re-arms a
            # short quiet timer; when the agent goes quiet (goodbye done), hang up.
            if self._after_place_order:
                self._arm_quiet_hangup()

        elif isinstance(message, AgentV1AgentStartedSpeaking):
            # New agent speech is starting — cancel any pending quiet hangup so
            # it doesn't fire mid-sentence. The next AgentAudioDone re-arms it.
            self._cancel_quiet_hangup()

        elif isinstance(message, AgentV1Error):
            logger.error(f'Agent error: {message.description} ({message.code})')

        elif isinstance(message, AgentV1Warning):
            logger.warning(f'Agent warning: {message.description} ({message.code})')

    async def _send_agent_audio(self, audio_bytes: bytes):
        """Forward raw agent audio back to Twilio as a base64 media event."""
        if not self.stream_sid:
            # No Twilio stream yet (greeting can beat Twilio's 'start' event) —
            # buffer a bounded amount and flush once the stream is known.
            if len(self._pre_stream_buffer) < 300:  # ~6s of 160-byte chunks
                self._pre_stream_buffer.append(audio_bytes)
            return
        payload = base64.b64encode(audio_bytes).decode('utf-8')
        await self.send(text_data=json.dumps({
            'event': 'media',
            'streamSid': self.stream_sid,
            'media': {'payload': payload},
        }))

    # ------------------------------------------------------------------
    # Function calls
    # ------------------------------------------------------------------

    async def _handle_function_call(self, event: AgentV1FunctionCallRequest):
        """Execute a function call from the agent and send the result back."""
        if not event.functions:
            return
        func = event.functions[0]
        name, call_id = func.name, func.id
        try:
            args = json.loads(func.arguments) if func.arguments else {}
        except json.JSONDecodeError:
            args = {}

        if name == 'place_order':
            result = await self._place_order(args)
        elif name == 'transfer_call':
            result = await self._transfer_call(args)
        elif name == 'end_conversation':
            result = {'status': 'call_ended', 'reason': args.get('reason', '')}
        else:
            logger.warning(f'Unknown function call: {name}')
            result = {'status': 'error', 'message': f'Unknown function: {name}'}

        logger.info(f'Function call: {name} → {result}')
        try:
            await self.dg_socket.send_function_call_response(
                AgentV1SendFunctionCallResponse(
                    type='FunctionCallResponse',
                    name=name,
                    id=call_id,
                    content=json.dumps(result),
                )
            )
        except Exception as e:
            # A transfer tears the agent socket down right after the update —
            # the response send can lose that race; the transfer already happened.
            logger.debug(f'Function response send failed for {name}: {e}')

        # place_order: the order is saved — the conversation is terminal. No
        # timer is armed here (a fixed hard timer could land while the goodbye
        # is still streaming); instead the AgentAudioDone handler above arms
        # the post-order quiet timer once the closing speech completes, and an
        # end_conversation call (below) arms HANGUP_DELAY as a second exit.
        if name == 'place_order' and result.get('status') == 'saved':
            self._after_place_order = True

        # transfer_call: the call now belongs to Twilio's <Dial> — tear down our
        # sockets as a separate task (never from inside the listen task: _cleanup
        # awaits self.listen_task, which would be the current task).
        if self._transferred:
            asyncio.create_task(self._finish_after_transfer())

        # end_conversation: the goodbye is already spoken — give any trailing
        # audio time to finish, then hang up. A closed agent socket (server-side
        # end_conversation) hits the same path via the listen-loop backstop.
        # After place_order this still arms (place_order no longer pre-schedules
        # a hangup), racing the quiet timer — whichever fires first wins.
        if name == 'end_conversation' and not self._hangup_scheduled:
            self._hangup_scheduled = True
            asyncio.create_task(self._hangup_after_delay())

    async def _place_order(self, args: dict) -> dict:
        """Save the order locally, send the SMS backup, and push to Clover."""
        def _save_sms_and_clover():
            order = save_order_from_agent(args, call_sid=self.call_sid)
            if not order:
                return None, None, None
            sms_sid = send_order_sms(order)          # Twilio SMS backup — unchanged
            clover_id = send_order_to_clover(order)  # Clover push — best-effort, never blocks
            return order, sms_sid, clover_id

        try:
            order, sms_sid, clover_id = await sync_to_async(
                _save_sms_and_clover, thread_sensitive=False
            )()
            if order:
                logger.info(
                    f'Order #{order.id} saved; SMS={sms_sid}; Clover={clover_id or "failed/not configured"}'
                )
                return {'status': 'saved', 'order_id': order.id, 'total': str(order.total)}
            logger.error('Failed to save order from function args')
            return {'status': 'error', 'message': 'Order could not be saved'}
        except Exception as e:
            logger.error(f'Order save error: {e}')
            return {'status': 'error', 'message': str(e)}

    async def _transfer_call(self, args: dict) -> dict:
        """Cold-transfer the call to a human via a REST TwiML update.

        The update replaces the <Connect><Stream> TwiML with an announcement
        <Say> + <Dial> to TRANSFER_PHONE. Twilio then stops the media stream
        (we get a 'stop' event and the WS closes) and owns the call from here
        on, so no server-side hangup path may run afterwards — that would kill
        the bridged call. The destination comes from settings; the model never
        supplies a phone number.
        """
        if self._transferred:
            return {'status': 'transferring'}
        if not transfer_enabled():
            return {'status': 'error', 'message': 'Transfer is not available right now'}
        if not self.call_sid:
            return {'status': 'error', 'message': 'No active call to transfer'}

        # Neutralize every server-side hangup path BEFORE touching the call:
        self._hangup_scheduled = True     # listen-loop finally + end_conversation arming
        self._cancel_quiet_hangup()       # post-order quiet timer
        self._transferred = True          # _hangup_now guard: skip REST status=completed

        def _update():
            client = get_twilio_client()
            twiml = build_transfer_twiml(
                settings.TRANSFER_PHONE, action_url=self._transfer_result_url)
            client.calls(self.call_sid).update(twiml=str(twiml))
            logger.info(f'📞 Transfer TwiML sent for call {self.call_sid}')

        try:
            await sync_to_async(_update, thread_sensitive=False)()
        except Exception as e:
            # Transfer failed — the call is still ours. Restore normal endings.
            self._transferred = False
            self._hangup_scheduled = False
            if self._after_place_order:
                self._arm_quiet_hangup()
            logger.error(f'📞 Transfer failed for call {self.call_sid}: {e}')
            return {'status': 'error',
                    'message': 'Transfer failed — please continue helping the customer'}

        logger.info(f'📞 Call {self.call_sid} transferred to human')
        return {'status': 'transferring',
                'message': 'The call is being transferred to a staff member'}

    async def _finish_after_transfer(self):
        """Tear down the Deepgram agent socket and the Twilio WebSocket after a
        successful transfer, WITHOUT touching the call (Twilio now controls it
        via the <Dial> TwiML). Runs as its own task so _cleanup's
        `await self.listen_task` is legal."""
        await self._cleanup()
        await self.close()

    # ------------------------------------------------------------------
    # Hangup + cleanup
    # ------------------------------------------------------------------

    def _cancel_quiet_hangup(self):
        """Cancel a pending post-order quiet hangup (agent started speaking again)."""
        if self._quiet_hangup_task is not None:
            self._quiet_hangup_task.cancel()
            self._quiet_hangup_task = None

    def _arm_quiet_hangup(self):
        """Reset the post-order quiet timer — end the call POST_ORDER_QUIET_DELAY
        after the agent's last utterance following place_order."""
        self._cancel_quiet_hangup()
        self._quiet_hangup_task = asyncio.create_task(
            self._quiet_hangup_after(delay=POST_ORDER_QUIET_DELAY)
        )

    async def _quiet_hangup_after(self, delay: float):
        await asyncio.sleep(delay)
        if self._cleaned_up:
            return
        self._quiet_hangup_task = None  # this task just ran its timer — nothing to cancel
        logger.info('Post-order quiet period elapsed — ending call')
        await self._hangup_now()

    async def _hangup_after_delay(self, delay: float = HANGUP_DELAY):
        """Hang up after the agent's final audio has played."""
        await asyncio.sleep(delay)
        await self._hangup_now()

    async def _hangup_now(self):
        """Hang up the Twilio call via REST and close both sockets.

        After a successful transfer the TwiML update has already handed the
        call to Twilio — a REST status='completed' would kill the bridged
        call, so it is skipped (cleanup + close still run)."""
        if self._cleaned_up:
            return
        self._hangup_scheduled = True

        if not self._transferred:
            def _hangup():
                if not self.call_sid:
                    return
                client = get_twilio_client()
                try:
                    client.calls(self.call_sid).update(status='completed')
                    logger.info(f'Call {self.call_sid} hung up successfully')
                except Exception as e:
                    logger.error(f'Failed to hang up call {self.call_sid}: {e}')

            await sync_to_async(_hangup, thread_sensitive=False)()
        await self._cleanup()
        await self.close()

    async def _cleanup(self):
        """Idempotent teardown of the agent socket and listen task."""
        if self._cleaned_up:
            return
        self._cleaned_up = True
        self._cancel_quiet_hangup()

        if self.listen_task:
            self.listen_task.cancel()
            try:
                await self.listen_task
            except (asyncio.CancelledError, Exception):
                pass
            self.listen_task = None

        if self.dg_ctx is not None:
            try:
                await self.dg_ctx.__aexit__(None, None, None)
            except Exception as e:
                logger.debug(f'Agent socket close error: {e}')
            self.dg_ctx = None
            self.dg_socket = None
        logger.info('Deepgram agent connection closed')
