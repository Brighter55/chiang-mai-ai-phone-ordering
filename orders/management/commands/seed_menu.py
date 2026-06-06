"""
Management command to seed the database with sample menu items.
Usage: python manage.py seed_menu
"""

from django.core.management.base import BaseCommand
from orders.models import MenuItem


SAMPLE_MENU = [
    # Appetizers
    {'name': 'Spring Rolls', 'price': 6.00, 'category': 'Appetizers', 'description': 'Crispy rolls with vegetables and sweet chili sauce', 'modifiers': ['extra crispy', 'peanut sauce']},
    {'name': 'Chicken Wings', 'price': 9.00, 'category': 'Appetizers', 'description': '8 pieces, served with ranch or blue cheese', 'modifiers': ['mild', 'hot', 'BBQ', 'extra ranch']},
    {'name': 'Mozzarella Sticks', 'price': 7.00, 'category': 'Appetizers', 'description': 'Breaded mozzarella with marinara', 'modifiers': ['extra marinara']},
    {'name': 'Onion Rings', 'price': 5.00, 'category': 'Appetizers', 'description': 'Beer-battered onion rings', 'modifiers': ['ranch dip', 'spicy dip']},

    # Salads
    {'name': 'Caesar Salad', 'price': 9.00, 'category': 'Salads', 'description': 'Romaine, croutons, parmesan, caesar dressing', 'modifiers': ['add chicken +$3', 'add shrimp +$4', 'no croutons', 'dressing on side']},
    {'name': 'House Salad', 'price': 7.00, 'category': 'Salads', 'description': 'Mixed greens, tomatoes, cucumbers, onions', 'modifiers': ['ranch', 'balsamic', 'blue cheese dressing']},

    # Burgers
    {'name': 'Classic Cheeseburger', 'price': 12.00, 'category': 'Burgers', 'description': 'Angus beef patty, cheddar, lettuce, tomato, onion, pickle', 'modifiers': ['medium rare', 'medium', 'well done', 'no cheese', 'add bacon +$2', 'add avocado +$1.50']},
    {'name': 'Bacon Burger', 'price': 14.00, 'category': 'Burgers', 'description': 'Angus beef, thick-cut bacon, smoked gouda, BBQ sauce', 'modifiers': ['medium rare', 'medium', 'well done', 'no bacon', 'extra bacon +$2']},
    {'name': 'Mushroom Swiss Burger', 'price': 13.00, 'category': 'Burgers', 'description': 'Angus beef, sautéed mushrooms, Swiss cheese, garlic aioli', 'modifiers': ['medium rare', 'medium', 'well done', 'add bacon +$2']},

    # Sandwiches
    {'name': 'Grilled Chicken Sandwich', 'price': 11.00, 'category': 'Sandwiches', 'description': 'Grilled chicken breast, lettuce, tomato, honey mustard', 'modifiers': ['add cheese +$1', 'add bacon +$2', 'no tomato']},
    {'name': 'BLT', 'price': 9.00, 'category': 'Sandwiches', 'description': 'Bacon, lettuce, tomato on toasted white bread', 'modifiers': ['add avocado +$1.50', 'extra bacon +$2']},
    {'name': 'Philly Cheesesteak', 'price': 13.00, 'category': 'Sandwiches', 'description': 'Sliced steak, melted provolone, peppers, onions', 'modifiers': ['add mushrooms', 'no onions', 'no peppers']},

    # Pasta
    {'name': 'Spaghetti Marinara', 'price': 11.00, 'category': 'Pasta', 'description': 'Classic marinara sauce over spaghetti', 'modifiers': ['add meatballs +$3', 'add chicken +$3', 'extra parmesan']},
    {'name': 'Fettuccine Alfredo', 'price': 13.00, 'category': 'Pasta', 'description': 'Creamy alfredo sauce, parmesan, garlic bread on side', 'modifiers': ['add chicken +$3', 'add shrimp +$4', 'add broccoli']},

    # Sides
    {'name': 'French Fries', 'price': 4.00, 'category': 'Sides', 'description': 'Crispy golden fries', 'modifiers': ['extra crispy', 'loaded +$3', 'truffle fries +$2']},
    {'name': 'Coleslaw', 'price': 3.00, 'category': 'Sides', 'description': 'House-made creamy coleslaw', 'modifiers': []},
    {'name': 'Mac and Cheese', 'price': 5.00, 'category': 'Sides', 'description': 'Creamy three-cheese mac', 'modifiers': ['add bacon +$2']},

    # Drinks
    {'name': 'Soda', 'price': 2.50, 'category': 'Drinks', 'description': 'Coke, Sprite, Dr Pepper, or Lemonade', 'modifiers': ['Coke', 'Sprite', 'Dr Pepper', 'Lemonade', 'Diet Coke']},
    {'name': 'Iced Tea', 'price': 2.00, 'category': 'Drinks', 'description': 'Fresh-brewed sweet or unsweet', 'modifiers': ['sweet', 'unsweet', 'add lemon']},
    {'name': 'Bottled Water', 'price': 1.50, 'category': 'Drinks', 'description': 'Spring water', 'modifiers': []},

    # Desserts
    {'name': 'Chocolate Cake', 'price': 7.00, 'category': 'Desserts', 'description': 'Rich chocolate layer cake', 'modifiers': ['add ice cream +$2', 'warmed up']},
    {'name': 'Cheesecake', 'price': 7.00, 'category': 'Desserts', 'description': 'New York style cheesecake', 'modifiers': ['strawberry topping', 'chocolate drizzle']},
]


class Command(BaseCommand):
    help = 'Seed the database with sample menu items.'

    def handle(self, *args, **options):
        created = 0
        for item_data in SAMPLE_MENU:
            _, was_created = MenuItem.objects.get_or_create(
                name=item_data['name'],
                defaults=item_data,
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'Seeded {created} new menu items (total: {MenuItem.objects.count()})'))
