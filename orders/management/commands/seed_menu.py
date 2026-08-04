"""
Management command to seed the database with Chiang Mai restaurant menu items.
Usage: python manage.py seed_menu
"""

from django.core.management.base import BaseCommand
from orders.models import MenuItem


SAMPLE_MENU = [
    # Small Plates
    {'name': 'Gai Todd', 'price': 11.39, 'category': 'Small Plates', 'description': 'crispy fried garlic pepper chicken wings (Gluten Free)', 'modifiers': [], 'thai_name': 'ไก่ทอด', 'aliases': ['gai tod', 'guy todd', 'kai tod', 'fried chicken wings']},
    {'name': 'Nua Sawaan', 'price': 12.39, 'category': 'Small Plates', 'description': 'marinated flash fried coriander beef strips, sea salt, palm sugar [Gluten Free]', 'modifiers': [], 'thai_name': 'เนื้อสวรรค์', 'aliases': ['nua sawan', 'newa sawan', 'beef strips', 'heavenly beef']},
    {'name': 'Poh Piah', 'price': 6.19, 'category': 'Small Plates', 'description': 'Eggrolls [Can be made Vegan]', 'modifiers': ['vegetables', 'cheese', 'pork (+$3.09)', 'shrimps (+$3.09)'], 'thai_name': 'เปาะเปี๊ยะ', 'aliases': ['po pia', 'poh pia', 'paw pia', 'eggrolls', 'spring rolls']},
    {'name': 'Som Tum', 'price': 11.39, 'category': 'Small Plates', 'description': 'green papaya, carrot, tomatoes, peanuts [Vegan, Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot'], 'thai_name': 'ส้มตำ', 'aliases': ['som tam', 'som tum salad', 'papaya salad', 'som tum']},
    {'name': 'Steamed Dumplings', 'price': 9.29, 'category': 'Small Plates', 'description': 'Chicken veggie dumplings 6 pcs. with soy sauce', 'modifiers': [], 'thai_name': 'เกี๊ยวนึ่ง', 'aliases': ['dumplings', 'chicken dumplings', 'steam dumpling']},

    # Entree
    {'name': 'Drunken Noodles', 'price': 17.59, 'category': 'Entree', 'description': 'rice noodles, green beans, peppers, bean sprouts, basil leaves in garlic chili sauce [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดขี้เมา', 'aliases': ['pad kee mao', 'pad ki mao', 'drunken noodle', 'spicy noodles']},
    {'name': 'Fried rice', 'price': 16.49, 'category': 'Entree', 'description': 'egg, onions, garlic', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ข้าวผัด', 'aliases': ['khao pad', 'kao pat', 'fried rice']},
    {'name': 'Gaeng Hung Lay', 'price': 16.49, 'category': 'Entree', 'description': 'braised curry pork, garlic, ginger, steamed rice', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'แกงฮังเล', 'aliases': ['gang hung lay', 'gaeng hung lei', 'hung lay curry', 'braised pork curry']},
    {'name': 'Gra Dook Moo', 'price': 23.71, 'category': 'Entree', 'description': 'half-slab oven roasted baby back ribs, honey pepper, garlic marinade, steamed rice', 'modifiers': [], 'thai_name': 'กระดูกหมู', 'aliases': ['gra dook moo', 'baby back ribs', 'pork ribs', 'ribs', 'garlic moo', 'garlic pork', 'garlic ribs']},
    {'name': 'Khao Soi', 'price': 17.59, 'category': 'Entree', 'description': 'chicken drumsticks, red coconut curry, egg noodles', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ข้าวซอย', 'aliases': ['khao soi', 'kao soi', 'cow soy', 'kow soy', 'kalsoy', 'cosign', 'curry noodle soup', 'coconut curry noodles']},
    {'name': 'Larb Khua', 'price': 16.49, 'category': 'Entree', 'description': 'sauteed spicy minced pork, steamed rice, vegetables', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot'], 'thai_name': 'ลาบคั่ว', 'aliases': ['larb kua', 'laab', 'larb', 'spicy minced pork']},
    {'name': 'Nam Ngiaw', 'price': 17.59, 'category': 'Entree', 'description': 'minced pork, bite-size rib, tofu, tomato curry broth, rice vermicelli [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'น้ำเงี้ยว', 'aliases': ['nam ngiao', 'nam now', 'nam ngiaw', 'northern noodle soup', 'tomato noodle soup']},
    {'name': 'Pad See Ew', 'price': 17.59, 'category': 'Entree', 'description': 'rice noodles, egg, broccoli or green Asian veggies, garlic, sweet soy sauce [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'broccoli', 'Asian green veggies (gai lan)', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดซีอิ๊ว', 'aliases': ['pad see ew', 'pat see you', 'pad si ew', 'see ew noodles', 'soy sauce noodles']},
    {'name': 'Pad Thai', 'price': 17.59, 'category': 'Entree', 'description': 'egg, bean sprouts, green onions, pickled radish, peanuts [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดไทย', 'aliases': ['pat thai', 'put tie', 'pep tai', 'pad tie', 'pat tai']},
    {'name': 'Sai Oua', 'price': 13.49, 'category': 'Entree', 'description': 'grilled pork sausage, aromatic spices, vegetables, steamed rice [Gluten Free]', 'modifiers': [], 'thai_name': 'ไส้อั่ว', 'aliases': ['sai ua', 'sigh ooh ah', 'sai ooh ah', 'sigh ua', 'grilled sausage', 'thai sausage']},
    {'name': 'Spicy Basil', 'price': 16.49, 'category': 'Entree', 'description': 'onions, peppers, basil leaves in garlic chili sauce, steamed rice [Can be made Vegan]', 'modifiers': ['add fried egg (+$1.55)', '0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดกะเพรา', 'aliases': ['pad krapow', 'pad kra pao', 'pad ga prao', 'basil stir fry', 'spicy basil stir fry']},
    {'name': 'Spicy Eggplant', 'price': 17.59, 'category': 'Entree', 'description': 'onions, peppers, spicy in sweet bean sauce, steamed rice [Can be made Vegan]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดมะเขือยาว', 'aliases': ['pad makua', 'pad ma kuea', 'eggplant stir fry']},
    {'name': 'Stir-Fried Vegetables', 'price': 17.53, 'category': 'Entree', 'description': '', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ผัดผักรวม', 'aliases': ['pad pak ruam', 'stir fried veggies', 'stir fry vegetables', 'mixed vegetables']},
    {'name': 'Suki', 'price': 19.59, 'category': 'Entree', 'description': 'chicken and shrimps, or tofu, egg, clear noodles, napa, carrots, cabbages, celeries, green onions, cilantros, sesame in suki (bean) sauce [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'สุกี้', 'aliases': ['sukiyaki', 'thai suki']},

    # Authentic Thai Curry
    {'name': 'Kaeng Daeng', 'price': 17.59, 'category': 'Authentic Thai Curry', 'description': 'red curry chicken, bamboo shoots, peppers, basil leaves with steamed rice [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'แกงแดง', 'aliases': ['red curry', 'gang dang', 'gaeng dang', 'red chicken curry']},
    {'name': 'Kaeng Keaw Waan', 'price': 17.59, 'category': 'Authentic Thai Curry', 'description': 'green curry chicken, coriander, cumin, eggplants, peppers, basil leaves with steamed rice [Can be made Vegan] [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'chicken', 'tofu', 'vegetables', 'shrimp', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'แกงเขียวหวาน', 'aliases': ['green curry', 'gang kiew wan', 'gaeng keaw wan', 'green chicken curry']},
    {'name': 'Massaman Beef', 'price': 21.69, 'category': 'Authentic Thai Curry', 'description': 'traditional spiced braised beef, potatoes, onions, cashews [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'มัสมั่นเนื้อ', 'aliases': ['massaman', 'matsaman', 'massaman curry', 'beef curry']},
    {'name': 'Yellow Curry Chicken', 'price': 20.69, 'category': 'Authentic Thai Curry', 'description': 'simmered in coconut curry with onions and potatoes [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'แกงกะหรี่ไก่', 'aliases': ['yellow curry', 'gang garee gai', 'kaeng kari']},

    # Noodle Soups
    {'name': 'Chicken Noodle Soup', 'price': 14.49, 'category': 'Noodle Soups', 'description': 'rice noodles, onions, cilantros, bean sprouts with clear broth [Gluten Free]', 'modifiers': ['0 - no spice', '1 - mild', '2 - medium', '3 - hot', '4 - very hot', '5 - extra hot', 'add tofu (+$2.09)', 'add chicken (+$3.09)', 'add vegetables (+$2.09)', 'add shrimp (+$4.19)', 'add green beans (+$2.09)', 'add broccoli (+$3.09)', 'add mixed steamed vegetables (+$2.09)'], 'thai_name': 'ก๋วยเตี๋ยวไก่', 'aliases': ['kuay tiew gai', 'guay tiew gai', 'noodle soup', 'chicken soup']},

    # Beverages
    {'name': 'Blue Moon', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': []},
    {'name': 'Chasing Lions Cabernet 750 mL', 'price': 25.79, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['chasing lions', 'cabernet']},
    {'name': 'Crane Lake Cabernet 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['crane lake cabernet', 'crane lake red']},
    {'name': 'Crane Lake Chardonnay 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['crane lake chardonnay', 'crane lake white']},
    {'name': 'Crane Lake Pinot Grigio 175 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['crane lake pinot grigio', 'pinot grigio']},
    {'name': 'Crane Lake Pinot Grigio 750 mL', 'price': 19.59, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['crane lake pinot grigio large']},
    {'name': 'Dreamy Clouds 300 mL', 'price': 19.59, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['dreamy clouds']},
    {'name': 'Lucky Star Chardonnay 750 mL', 'price': 20.69, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['lucky star', 'lucky star chardonnay']},
    {'name': "Pareja's Pinot Noir 750 mL", 'price': 25.79, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['pareja', 'pinot noir']},
    {'name': 'Rihaku - Wandering Poet 300 mL', 'price': 24.79, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['rihaku', 'wandering poet', 'sake']},
    {'name': 'Sapporo', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['sapporo beer']},
    {'name': 'Singha', 'price': 7.29, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['singha beer', 'singha']},
    {'name': 'Tozai Living Jewel 300 mL', 'price': 15.49, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['tozai living jewel', 'living jewel']},
    {'name': 'Tozai Night Swim', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['tozai night swim', 'night swim']},
    {'name': 'Tozai Snow Maiden (Nigori) 300 mL', 'price': 15.49, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['tozai snow maiden', 'snow maiden', 'nigori']},
    {'name': 'Tsingtao', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['tsingtao beer']},
    {'name': 'Underwood Pinot Noir 250 mL', 'price': 6.19, 'category': 'Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['underwood', 'underwood pinot noir']},

    # NA Beverages
    {'name': 'Bottle water', 'price': 0.79, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['water', 'bottled water']},
    {'name': 'Coconut Juice', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': 'น้ำมะพร้าว', 'aliases': ['coconut water', 'nam maprao']},
    {'name': 'Coke', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['coca cola', 'coca-cola']},
    {'name': 'Diet Coke', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['diet coca cola']},
    {'name': 'Dr. Pepper', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['doctor pepper']},
    {'name': 'Ginger Ale', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': []},
    {'name': 'Green tea (hot)', 'price': 3.09, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': 'ชาเขียว', 'aliases': ['hot green tea']},
    {'name': 'Iced tea', 'price': 3.09, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['ice tea']},
    {'name': 'Pepsi', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': []},
    {'name': 'Perrier', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['sparkling water']},
    {'name': 'Sprite', 'price': 2.06, 'category': 'NA Beverages', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': []},
    {'name': 'Thai Iced Coffee', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': ['iced', 'no iced (+$1.00)'], 'thai_name': 'กาแฟเย็น', 'aliases': ['thai coffee', 'kaffee yen', 'iced coffee']},
    {'name': 'Thai Iced Tea', 'price': 5.19, 'category': 'NA Beverages', 'description': '', 'modifiers': ['iced', 'no iced (+$1.00)'], 'thai_name': 'ชาเย็น', 'aliases': ['thai tea', 'cha yen', 'iced tea thai']},

    # Specials
    {'name': 'Mango Sticky Rice', 'price': 12.37, 'category': 'Specials', 'description': '', 'modifiers': [], 'thai_name': 'ข้าวเหนียวมะม่วง', 'aliases': ['khao niew mamuang', 'sticky rice mango', 'mango rice']},

    # Side Orders
    {'name': 'Broccoli', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['steamed broccoli']},
    {'name': 'Fried Egg', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': 'ไข่ดาว', 'aliases': ['kai dao', 'fried egg']},
    {'name': 'Gra Dook Moo Sauce', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['rib sauce', 'dipping sauce']},
    {'name': 'Green beans', 'price': 2.06, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['steamed green beans']},
    {'name': 'Mixed Steamed Vegetables', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['steamed vegetables', 'mixed veggies']},
    {'name': 'Pad Thai Sauce', 'price': 1.55, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': []},
    {'name': 'Steamed Egg Noodle', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['egg noodles']},
    {'name': 'Steamed Rice Noodle', 'price': 1.03, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': '', 'aliases': ['rice noodles']},
    {'name': 'Sticky Rice', 'price': 3.09, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': 'ข้าวเหนียว', 'aliases': ['khao niew', 'sticky rice']},
    {'name': 'White Rice', 'price': 1.03, 'category': 'Side Orders', 'description': '', 'modifiers': [], 'thai_name': 'ข้าวสวย', 'aliases': ['steamed rice', 'plain rice', 'khao suay']},
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
