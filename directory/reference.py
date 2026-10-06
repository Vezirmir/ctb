"""Known countries and industries.

Spreadsheets and folder names are in Russian, the interface is in English and
Turkish. Each entry maps the Russian spellings used in the source files to the
English and Turkish names. Unknown names are still imported as-is and can be
translated later in the admin.
"""

# (ISO code, English, Turkish, Russian spellings)
COUNTRIES = [
    ("RU", "Russia", "Rusya", ["Россия", "РФ", "Российская Федерация"]),
    ("BY", "Belarus", "Belarus", ["Беларусь", "Белоруссия", "РБ"]),
    ("KZ", "Kazakhstan", "Kazakistan", ["Казахстан", "РК"]),
    ("UZ", "Uzbekistan", "Özbekistan", ["Узбекистан"]),
    ("KG", "Kyrgyzstan", "Kırgızistan", ["Кыргызстан", "Киргизия"]),
    ("TJ", "Tajikistan", "Tacikistan", ["Таджикистан"]),
    ("TM", "Turkmenistan", "Türkmenistan", ["Туркменистан"]),
    ("AZ", "Azerbaijan", "Azerbaycan", ["Азербайджан"]),
    ("AM", "Armenia", "Ermenistan", ["Армения"]),
    ("GE", "Georgia", "Gürcistan", ["Грузия"]),
    ("MD", "Moldova", "Moldova", ["Молдова", "Молдавия"]),
    ("UA", "Ukraine", "Ukrayna", ["Украина"]),
    ("TR", "Türkiye", "Türkiye", ["Турция"]),
    ("LV", "Latvia", "Letonya", ["Латвия"]),
    ("LT", "Lithuania", "Litvanya", ["Литва"]),
    ("EE", "Estonia", "Estonya", ["Эстония"]),
    ("DE", "Germany", "Almanya", ["Германия"]),
    ("CN", "China", "Çin", ["Китай"]),
]

# (English, Turkish, Russian spellings)
INDUSTRIES = [
    ("Automotive", "Otomotiv", ["Автомобильная", "Автомобильная промышленность", "Автопром"]),
    ("Home appliances", "Beyaz Eşya", ["Бытовая техника"]),
    ("Railway", "Demiryolu", ["Железнодорожная", "ЖД"]),
    ("Agricultural machinery", "Tarım makineleri", ["Сельхозтехника", "Сельскохозяйственная техника"]),
    ("Agriculture", "Tarım", ["Сельское хозяйство", "Сельскохозяйственная"]),
    ("Construction", "İnşaat", ["Строительная", "Строительство"]),
    ("Food", "Gıda", ["Пищевая", "Продукты питания"]),
    ("Textile", "Tekstil", ["Текстильная", "Текстиль", "Лёгкая промышленность"]),
    ("Furniture", "Mobilya", ["Мебельная", "Мебель"]),
    ("Medical", "Tıbbi", ["Медицинская", "Медицина"]),
    ("Energy", "Enerji", ["Энергетика", "Энергетическая"]),
    ("Chemical", "Kimya", ["Химическая", "Химия"]),
    ("Metallurgy", "Metalurji", ["Металлургия", "Металлургическая"]),
    ("Machinery", "Makine", ["Машиностроение", "Машиностроительная"]),
    ("Packaging", "Ambalaj", ["Упаковка", "Упаковочная"]),
]
