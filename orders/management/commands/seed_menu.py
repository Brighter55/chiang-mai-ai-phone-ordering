"""
Management command to seed the database with Chiang Mai restaurant menu items.
Usage: python manage.py seed_menu
"""

from django.core.management.base import BaseCommand
from orders.models import MenuItem


SAMPLE_MENU = [
    # Small Plates
    {'name': 'Gai Todd', 'price': 11.39, 'category': 'Small Plates', 'description': 'crispy fried garlic pepper chicken wings (Gluten Free)', 'modifiers': [], 'aliases': ['gai tod', 'guy todd', 'fried chicken wings']},
    {'name': 'Nua Sawaan', 'price': 12.39, 'category': 'Small Plates', 'description': 'marinated flash fried coriander beef strips, sea salt, palm sugar [Gluten Free]', 'modifiers': [], 'aliases': ['nua sawan', 'newa sawan', 'beef strips']},
    {'name': 'Poh Piah', 'price': 6.19, 'category': 'Small Plates', 'description': 'Eggrolls [Can be made Vegan]', 'modifiers': ['vegetables', 'cheese', 'pork (+$3.09)', 'shrimps (+$3.09)'], 'aliases': ['po pia', 'poh pia', 'eggrolls', 'spring rolls']},
    {'name': 'Som Tum', 'price': 11.39, 'category': 'Small Plates', 'description': 'green papaya, carrot, tomatoes, peanuts [Vegan, Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot'], 'aliases': ['som tam', 'som tum salad', 'papaya salad', 'som tum']},
    {'name': 'Steamed Dumplings', 'price': 9.29, 'category': 'Small Plates', 'description': 'Chicken veggie dumplings 6 pcs. with soy sauce', 'modifiers': []},

    # Entree
    {'name': 'Drunken Noodles', 'price': 17.59, 'category': 'Entree', 'description': 'rice noodles, green beans, peppers, bean sprouts, basil leaves in garlic chili sauce [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},
    {'name': 'Fried rice', 'price': 16.49, 'category': 'Entree', 'description': 'egg, onions, garlic', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},
    {'name': 'Gaeng Hung Lay', 'price': 16.49, 'category': 'Entree', 'description': 'braised curry pork, garlic, ginger, steamed rice', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['gang hung lay', 'gaeng hung lei', 'hung lay curry', 'braised pork curry']},
    {'name': 'Gra Dook Moo', 'price': 23.71, 'category': 'Entree', 'description': 'half-slab oven roasted baby back ribs, honey pepper, garlic marinade, steamed rice', 'modifiers': [], 'aliases': ['gra dook moo', 'baby back ribs', 'pork ribs']},
    {'name': 'Khao Soi', 'price': 17.59, 'category': 'Entree', 'description': 'chicken drumsticks, red coconut curry, egg noodles', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['khao soi', 'kao soi', 'cow soy', 'kalsoy', 'cosign']},
    {'name': 'Larb Khua', 'price': 16.49, 'category': 'Entree', 'description': 'sauteed spicy minced pork, steamed rice, vegetables', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot'], 'aliases': ['larb kua', 'laab', 'spicy minced pork']},
    {'name': 'Nam Ngiaw', 'price': 17.59, 'category': 'Entree', 'description': 'minced pork, bite-size rib, tofu, tomato curry broth, rice vermicelli [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['nam ngiao', 'nam now', 'northern noodle soup']},
    {'name': 'Pad See Ew', 'price': 17.59, 'category': 'Entree', 'description': 'rice noodles, egg, broccoli or green Asian veggies, garlic, sweet soy sauce [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'broccoli', 'Asian green veggies (gai lan)', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['pad see ew', 'pat see you', 'see ew noodles', 'soy sauce noodles']},
    {'name': 'Pad Thai', 'price': 17.59, 'category': 'Entree', 'description': 'egg, bean sprouts, green onions, pickled radish, peanuts [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['pat thai', 'put tie', 'pep tai']},
    {'name': 'Sai Oua', 'price': 13.49, 'category': 'Entree', 'description': 'grilled pork sausage, aromatic spices, vegetables, steamed rice [Gluten Free]', 'modifiers': [], 'aliases': ['sai ua', 'sigh ooh ah', 'grilled sausage']},
    {'name': 'Spicy Basil', 'price': 16.49, 'category': 'Entree', 'description': 'onions, peppers, basil leaves in garlic chili sauce, steamed rice [Can be made Vegan]', 'modifiers': ['add fried egg (+$1.55)', '0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},
    {'name': 'Spicy Eggplant', 'price': 17.59, 'category': 'Entree', 'description': 'onions, peppers, spicy in sweet bean sauce, steamed rice [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},
    {'name': 'Stir-Fried Vegetables', 'price': 17.53, 'category': 'Entree', 'description': '', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},
    {'name': 'Suki', 'price': 19.59, 'category': 'Entree', 'description': 'chicken and shrimps, or tofu, egg, clear noodles, napa, carrots, cabbages, celeries, green onions, cilantros, sesame in suki (bean) sauce [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},

    # Authentic Thai Curry
    {'name': 'Kaeng Daeng', 'price': 17.59, 'category': 'Authentic Thai Curry', 'description': 'red curry chicken, bamboo shoots, peppers, basil leaves with steamed rice [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['red curry', 'gang dang', 'gaeng dang']},
    {'name': 'Kaeng Keaw Waan', 'price': 17.59, 'category': 'Authentic Thai Curry', 'description': 'green curry chicken, coriander, cumin, eggplants, peppers, basil leaves with steamed rice [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['green curry', 'gang kiew wan', 'gaeng keaw wan']},
    {'name': 'Massaman Beef', 'price': 21.69, 'category': 'Authentic Thai Curry', 'description': 'traditional spiced braised beef, potatoes, onions, cashews [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'aliases': ['massaman', 'matsaman', 'massaman curry']},
    {'name': 'Yellow Curry Chicken', 'price': 20.69, 'category': 'Authentic Thai Curry', 'description': 'simmered in coconut curry with onions and potatoes [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},

    # Noodle Soups
    {'name': 'Chicken Noodle Soup', 'price': 14.49, 'category': 'Noodle Soups', 'description': 'rice noodles, onions, cilantros, bean sprouts with clear broth [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)']},

    # Beverages
    {'name': 'Blue Moon', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Chasing Lions Cabernet 750 mL', 'price': 25.79, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Crane Lake Cabernet 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Crane Lake Chardonnay 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Crane Lake Pinot Grigio 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Crane Lake Pinot Grigio 750 mL', 'price': 19.59, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Dreamy Clouds 300 mL', 'price': 19.59, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Lucky Star Chardonnay 750 mL', 'price': 20.69, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': "Pareja's Pinot Noir 750 mL", 'price': 25.79, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Rihaku - Wandering Poet 300 mL', 'price': 24.79, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Sapporo', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Singha', 'price': 7.29, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Tozai Living Jewel 300 mL', 'price': 15.49, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Tozai Night Swim', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Tozai Snow Maiden (Nigori) 300 mL', 'price': 15.49, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Tsingtao', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},
    {'name': 'Underwood Pinot Noir 250 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': []},

    # NA Beverages
    {'name': 'Bottle water', 'price': 0.79, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Coconut Juice', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Coke', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Diet Coke', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Dr. Pepper', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Ginger Ale', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Green tea (hot)', 'price': 3.09, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Iced tea', 'price': 3.09, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Pepsi', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Perrier', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Sprite', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': []},
    {'name': 'Thai Iced Coffee', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': ['iced', 'no iced (+$1.00)']},
    {'name': 'Thai Iced Tea', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': ['iced', 'no iced (+$1.00)']},

    # Specials
    {'name': 'Mango Sticky Rice', 'price': 12.37, 'category': 'Specials', 'description': '', 'modifiers': []},

    # Side Orders
    {'name': 'Broccoli', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Fried Egg', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Gra Dook Moo Sauce', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Green beans', 'price': 2.06, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Mixed Steamed Vegetables', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Pad Thai Sauce', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Steamed Egg Noodle', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Steamed Rice Noodle', 'price': 1.03, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'Sticky Rice', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': []},
    {'name': 'White Rice', 'price': 1.03, 'category': 'Side Orders', 'description': '', 'modifiers': []},
]


class Command(BaseCommand):
    help = 'Seed the database with Chiang Mai restaurant menu items.'

    def handle(self, *args, **options):
        menu_names = {item['name'] for item in SAMPLE_MENU}

        # Remove items no longer in the menu
        stale = MenuItem.objects.exclude(name__in=menu_names)
        stale_count = stale.count()
        if stale_count:
            stale.delete()
            self.stdout.write(self.style.WARNING(f'Removed {stale_count} stale menu items'))

        # Upsert current menu items (create new + update existing)
        created = 0
        updated = 0
        for item_data in SAMPLE_MENU:
            item, was_created = MenuItem.objects.get_or_create(
                name=item_data['name'],
                defaults=item_data,
            )
            if was_created:
                created += 1
            else:
                # Update existing item with any changed fields (e.g. aliases, prices)
                changed = False
                for key, value in item_data.items():
                    if key != 'name' and getattr(item, key) != value:
                        setattr(item, key, value)
                        changed = True
                if changed:
                    item.save()
                    updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Seeded {created} new, {updated} updated (total: {MenuItem.objects.count()})'
        ))
