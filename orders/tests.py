"""
Tests for the transfer-to-human feature: phone normalization, the loop guard,
the cold-transfer TwiML builder, and the conditional agent function/prompt.
"""

from django.test import TestCase, override_settings

from .agent import build_functions, build_system_prompt
from .transfer import (
    TRANSFER_ANNOUNCEMENT,
    build_transfer_twiml,
    normalize_phone,
    transfer_enabled,
)


class NormalizePhoneTests(TestCase):
    def test_plus_e164(self):
        self.assertEqual(normalize_phone('+13148877942'), '3148877942')

    def test_dashes_and_spaces(self):
        self.assertEqual(normalize_phone('314-887-7942'), '3148877942')
        self.assertEqual(normalize_phone('+1 314 887 7942'), '3148877942')

    def test_strips_leading_us_one(self):
        self.assertEqual(normalize_phone('1(314)8877942'), '3148877942')

    def test_garbage_and_empty(self):
        self.assertEqual(normalize_phone('garbage'), '')
        self.assertEqual(normalize_phone(''), '')
        self.assertEqual(normalize_phone(None), '')


class TransferGuardTests(TestCase):
    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='+13149546598',
    )
    def test_same_as_restaurant_number_disabled(self):
        # Same number as RESTAURANT_PHONE but formatted differently — the
        # AT&T no-answer forwarding loop guard must catch it.
        self.assertFalse(transfer_enabled())

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='+1 314-887-7942',
    )
    def test_same_as_twilio_number_disabled(self):
        self.assertFalse(transfer_enabled())

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='+13145551234',
    )
    def test_distinct_number_enabled(self):
        self.assertTrue(transfer_enabled())

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='',
    )
    def test_unset_disabled(self):
        self.assertFalse(transfer_enabled())


class TransferTwimlTests(TestCase):
    def test_basic_structure(self):
        twiml = str(build_transfer_twiml('+13145551234'))
        self.assertIn('<Response>', twiml)
        self.assertIn('<Say', twiml)
        self.assertIn(TRANSFER_ANNOUNCEMENT, twiml)
        self.assertIn('<Dial', twiml)
        self.assertIn('+13145551234', twiml)
        self.assertIn('timeout="25"', twiml)

    def test_no_action_url_means_no_action_attribute(self):
        twiml = str(build_transfer_twiml('+13145551234'))
        self.assertNotIn('action=', twiml)

    def test_action_url_included_when_provided(self):
        twiml = str(build_transfer_twiml(
            '+13145551234', action_url='https://example.com/twilio/transfer-result/'))
        self.assertIn('action="https://example.com/twilio/transfer-result/"', twiml)


class BuildFunctionsTests(TestCase):
    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='+13145551234',
    )
    def test_transfer_call_exposed_when_enabled(self):
        names = [f.name for f in build_functions()]
        self.assertEqual(names, ['place_order', 'end_conversation', 'transfer_call'])

        transfer_call = next(f for f in build_functions() if f.name == 'transfer_call')
        # Anti toll-fraud: the model can never supply a destination.
        self.assertNotIn('destination', transfer_call.parameters['properties'])
        self.assertNotIn('phone', transfer_call.parameters['properties'])
        self.assertEqual(transfer_call.parameters['required'], [])

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='',
    )
    def test_transfer_call_hidden_when_disabled(self):
        names = [f.name for f in build_functions()]
        self.assertEqual(names, ['place_order', 'end_conversation'])
        self.assertNotIn('transfer_call', names)


class BuildPromptTests(TestCase):
    # The enabled/disabled dynamic blocks appended last in build_system_prompt.
    ENABLED_MARKER = 'This overrides every other instruction in this prompt, including "Ending the call".'
    DISABLED_MARKER = 'no `transfer_call` function is available'

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='+13145551234',
    )
    def test_transfer_instructions_present_when_enabled(self):
        prompt = build_system_prompt()
        self.assertIn('## Transferring to a Human', prompt)
        self.assertIn(self.ENABLED_MARKER, prompt)
        self.assertNotIn(self.DISABLED_MARKER, prompt)

    @override_settings(
        TWILIO_PHONE_NUMBER='+13148877942',
        RESTAURANT_PHONE='+13149546598',
        TRANSFER_PHONE='',
    )
    def test_decline_instructions_present_when_disabled(self):
        prompt = build_system_prompt()
        self.assertIn(self.DISABLED_MARKER, prompt)
        self.assertNotIn(self.ENABLED_MARKER, prompt)
