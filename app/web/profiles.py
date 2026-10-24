"""Industry profiles are navigation groups; analysis remains company-specific."""
PROFILE_DEFINITIONS = (
    ('automotive', 'Автозапчасти', 'Торговля автомобилями, деталями и принадлежностями', 'А', '#ef3124'),
    ('appliances', 'Бытовая техника', 'Оптовая торговля бытовой техникой и электроникой', 'Б', '#7656c7'),
    ('logistics', 'Логистика', 'Перевозки и вспомогательная транспортная деятельность', 'Л', '#147b74'),
    ('real_estate', 'Недвижимость', 'Аренда и операции с недвижимым имуществом', 'Н', '#a66924'),
    ('other', 'Другие отрасли', 'Компании с другими видами деятельности', 'Д', '#586478'),
)


def profile_id(okved):
    code = str(okved or '')
    if code.startswith('45'):
        return 'automotive'
    if code.startswith(('46.43', '46.51', '46.52')):
        return 'appliances'
    if code.startswith(('49', '50', '51', '52', '53')):
        return 'logistics'
    if code.startswith('68'):
        return 'real_estate'
    return 'other'


def list_profiles(companies):
    return [dict(id=key, title=title, description=description, initial=initial, color=color,
                 company_ids=[c['id'] for c in companies if profile_id(c['okved']) == key])
            for key, title, description, initial, color in PROFILE_DEFINITIONS
            if any(profile_id(c['okved']) == key for c in companies)]
