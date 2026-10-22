# Структура `companies_analytics.json`

Файл содержит три группы компаний-клиентов и аналитику по их платежам. JSON сохранён в UTF-8 с отступами, суммы указаны в рублях, доли — в процентах.

## 1. Верхний уровень

```json
{
  "meta": { ... },
  "groups": [ ... ]
}
```

| Поле | Тип | Описание |
|---|---|---|
| `meta` | object | Метаданные: источники, статистика очистки, правила выбора групп и метрик. |
| `groups` | array | Ровно три выбранные группы. Элемент массива описан в разделе 2. |

## 2. Объект группы

```json
{
  "group_id": "group_132767_sb",
  "selection": { ... },
  "summary": { ... },
  "companies": [ ... ]
}
```

| Поле | Тип | Описание |
|---|---|---|
| `group_id` | string | Идентификатор группы компаний из `GROUP_ID`. |
| `selection` | object | Почему группа выбрана и её агрегированные характеристики. |
| `summary` | object | Состав группы и суммарная транзакционная статистика. |
| `companies` | array | Компании группы. Элемент массива описан в разделе 3. |

### 2.1. `selection`

| Поле | Тип | Описание |
|---|---|---|
| `rank` | integer | Место группы в итоговой тройке (1–3). Ранжирование по суммарной выручке. |
| `okved_section.code` | string | Код раздела ОКВЭД (A–U) основного вида деятельности группы. |
| `okved_section.name` | string | Наименование раздела ОКВЭД. |
| `okved_class` | string | Двузначный класс ОКВЭД, преобладающий в группе по выручке. |
| `main_okved.code` | string | Код ОКВЭД, преобладающий в группе по выручке. |
| `main_okved.name` | string | Наименование этого кода ОКВЭД. |
| `headquarters_region` | string | Регион, преобладающий в группе по выручке. |
| `headquarters_city` | string | Город, преобладающий в группе по выручке. |
| `group_edges_count` | integer | Число уникальных транзакционных связей группы (строк после очистки, где хотя бы одна сторона — участник группы). |
| `min_company_edges_count` | integer | Минимальное число связей среди компаний группы. |
| `reason` | string | Текстовое обоснование выбора группы. |

«Преобладающий» означает значение с максимальной суммарной выручкой внутри группы, а не первую строку датасета. Это важно для смешанных групп.

### 2.2. `summary.composition`

| Поле | Тип | Описание |
|---|---|---|
| `companies_count` | integer | Число компаний в группе. |
| `total_revenue_rub` | integer | Суммарная годовая выручка компаний группы, ₽. |
| `total_revenue_bn_rub` | number | То же в млрд ₽ (для отображения). |
| `regions` | array[string] | Все регионы регистрации компаний группы. |
| `cities` | array[string] | Все города регистрации компаний группы. |
| `okved_sections` | array[object] | Разделы ОКВЭД компаний группы: `{code, name, companies_count}`. |
| `okved_classes` | array[object] | Точные ОКВЭД компаний группы: `{code, name, companies_count}`. |

### 2.3. `summary.transactions`

| Поле | Тип | Описание |
|---|---|---|
| `edges_count` | integer | Число уникальных связей, в которых участвует хотя бы одна компания группы. Внутригрупповая связь считается один раз. |
| `turnover_rub` | integer | Суммарный оборот по этим связям, ₽. |
| `payments_count` | integer | Сумма `PAY_CNT` по этим связям (фактическое число платежей). |
| `unique_counterparties_count` | integer | Все уникальные контрагенты группы: внешние + участники группы, с которыми есть внутригрупповые связи. |
| `external_counterparties_count` | integer | Уникальные контрагенты вне группы. |
| `intragroup_counterparties_count` | integer | Участники группы, которые выступают контрагентами во внутригрупповых связях. |
| `intragroup_amount_rub` | integer | Оборот по связям, где обе стороны входят в группу, ₽. |
| `intragroup_share_pct` | number | Доля внутригруппового оборота в `turnover_rub`, %. |

## 3. Объект компании

```json
{
  "company_id": "U_128194",
  "main": { ... },
  "payments": { ... }
}
```

| Поле | Тип | Описание |
|---|---|---|
| `company_id` | string | `SYNTHETIC_U` компании. |
| `main` | object | Основные данные компании (п. 2.1 задания). |
| `payments` | object | Метрики по транзакциям. |

### 3.1. `main`

| Поле | Тип | Описание |
|---|---|---|
| `okved.code` | string | Код основного ОКВЭД. |
| `okved.name` | string | Наименование основного ОКВЭД. |
| `okved.section.code` | string | Код раздела ОКВЭД (A–U). |
| `okved.section.name` | string | Наименование раздела ОКВЭД. |
| `bank_services.cash_settlement_rko` | boolean \| null | Наличие расчётно-кассового обслуживания. |
| `bank_services.bank_guarantees` | boolean \| null | Наличие банковских гарантий. |
| `bank_services.loans` | boolean \| null | Наличие кредитных продуктов. |
| `bank_services.leasing` | boolean \| null | Наличие лизинговых продуктов. |
| `bank_services.deposits` | boolean \| null | Наличие депозитных продуктов. |
| `bank_services.salary_project` | boolean \| null | Наличие зарплатного проекта. |
| `bank_services.factoring` | boolean \| null | Наличие факторинга (дополнительное поле, есть в исходных данных). |
| `location.city` | string | Город регистрации. |
| `location.region` | string | Регион регистрации. |
| `ownership_form` | string | Форма собственности (`OKFS_NAME`). |
| `annual_revenue_rub` | integer | Годовая выручка, ₽. |
| `annual_revenue_bn_rub` | number | Годовая выручка в млрд ₽. |
| `foreign_trade_countries` | array[string] | Страны из `FTS_COUNTRY_NAME`; пустой массив, если данных нет. |
| `business_stage` | string \| null | Стадия развития компании (`ECO_MARK_LABEL`). |
| `client_type` | string | Тип клиента; в выбранных группах всегда `CLIENT`. |
| `group_id` | string | Идентификатор группы. |

### 3.2. `payments.totals`

| Поле | Тип | Описание |
|---|---|---|
| `incoming_amount_rub` | integer | Сумма входящих платежей компании, ₽. |
| `outgoing_amount_rub` | integer | Сумма исходящих платежей компании, ₽. |
| `turnover_rub` | integer | `incoming_amount_rub + outgoing_amount_rub`. |
| `incoming_payments_count` | integer | Сумма `PAY_CNT` по входящим связям. |
| `outgoing_payments_count` | integer | Сумма `PAY_CNT` по исходящим связям. |
| `edges_count` | integer | Число уникальных связей компании (входящие + исходящие строки). |
| `unique_counterparties_count` | integer | Уникальные контрагенты, включая внутригрупповых. |
| `external_counterparties_count` | integer | Контрагенты вне своей группы. |
| `intragroup_counterparties_count` | integer | Участники своей группы среди контрагентов. |
| `intragroup_amount_rub` | integer | Оборот с внутригрупповыми контрагентами, ₽. |
| `intragroup_share_pct` | number | Доля внутригруппового оборота, %. |
| `average_edge_amount_rub` | integer | Средний оборот на одну связь: `turnover_rub / edges_count`. |

Внутригрупповые платежи **включены** во все метрики. Признак `is_intragroup` позволяет отфильтровать их на стороне приложения.

### 3.3. `payments.counterparties`

| Поле | Тип | Описание |
|---|---|---|
| `unique_count` | integer | Число уникальных контрагентов. |
| `top_1_share_pct` | number | Доля крупнейшего контрагента в обороте, %. |
| `top_3_share_pct` | number | Суммарная доля топ-3 контрагентов, %. |
| `hhi` | number | Индекс Herfindahl–Hirschman по долям контрагентов, шкала 0–10 000. |
| `top_3` | array[object] | Топ-3 контрагента по обороту. |

Элемент `top_3`:

| Поле | Тип | Описание |
|---|---|---|
| `company_id` | string | `SYNTHETIC_U` контрагента. |
| `okved_code` | string | Основной ОКВЭД контрагента. |
| `okved_name` | string | Наименование ОКВЭД контрагента. |
| `region` | string | Регион регистрации контрагента. |
| `city` | string | Город регистрации контрагента. |
| `is_intragroup` | boolean | Контрагент входит в ту же группу. |
| `incoming_amount_rub` | integer | Получено от контрагента, ₽. |
| `outgoing_amount_rub` | integer | Отправлено контрагенту, ₽. |
| `turnover_rub` | integer | Суммарный оборот с контрагентом, ₽. |
| `payments_count` | integer | Сумма `PAY_CNT` по связям с контрагентом. |
| `share_pct` | number | Доля контрагента в общем обороте компании, %. |

### 3.4. `payments.top_okved`

Топ-3 **класса** ОКВЭД контрагентов (первые две цифры кода) по сумме оборота. Внутри каждого класса приведены топ-3 точных кода.

| Поле | Тип | Описание |
|---|---|---|
| `okved_class` | string | Двузначный класс ОКВЭД. |
| `okved_name` | string | Наименование класса ОКВЭД. |
| `counterparties_count` | integer | Число уникальных контрагентов этого класса. |
| `amount_rub` | integer | Оборот с контрагентами класса, ₽. |
| `share_pct` | number | Доля класса в общем обороте компании, %. |
| `top_codes` | array[object] | Топ-3 точных ОКВЭД внутри класса. |

Элемент `top_codes`:

| Поле | Тип | Описание |
|---|---|---|
| `okved_code` | string | Точный код ОКВЭД. |
| `okved_name` | string | Наименование точного кода. |
| `counterparties_count` | integer | Число контрагентов с этим кодом. |
| `amount_rub` | integer | Оборот с ними, ₽. |
| `share_pct` | number | Доля в общем обороте компании, %. |

### 3.5. `payments.geography`

| Поле | Тип | Описание |
|---|---|---|
| `top_regions` | array[object] | Топ-3 региона контрагентов по обороту. |
| `top_cities` | array[object] | Топ-3 города контрагентов по обороту. |

Элемент `top_regions`:

| Поле | Тип | Описание |
|---|---|---|
| `region` | string | Регион регистрации контрагента. |
| `counterparties_count` | integer | Число уникальных контрагентов региона. |
| `amount_rub` | integer | Оборот с ними, ₽. |
| `share_pct` | number | Доля региона в общем обороте компании, %. |

Элемент `top_cities` аналогичен, но содержит поле `city` вместо `region`.

### 3.6. `payments.two_way_links`

| Поле | Тип | Описание |
|---|---|---|
| `count` | integer | Число контрагентов, с которыми есть и входящие, и исходящие платежи. |
| `share_pct` | number | Доля таких контрагентов среди всех уникальных, %. |
| `top_3` | array[object] | Топ-3 двусторонних контрагентов по обороту. |

Элемент `top_3` содержит: `company_id`, `okved_code`, `okved_name`, `region`, `incoming_amount_rub`, `outgoing_amount_rub`, `turnover_rub`.

## 4. Метрики: определения

- **Оборот с контрагентом** — сумма входящих и исходящих платежей между компанией и этим контрагентом.
- **`top_1_share_pct`** — оборот крупнейшего контрагента / общий оборот компании × 100.
- **`top_3_share_pct`** — сумма оборотов трёх крупнейших контрагентов / общий оборот × 100.
- **`hhi`** — сумма квадратов долей контрагентов × 10 000. Чем ближе к 10 000, тем выше концентрация.
- **`top_okved`** — агрегация по классу ОКВЭД (2 цифры), внутри класса — топ-3 точных кода.
- **География** — по региону и городу регистрации контрагента.
- **Двусторонние связи** — контрагенты, у которых одновременно `incoming_amount_rub > 0` и `outgoing_amount_rub > 0`.
- **Внутригрупповой оборот** — связи, где обе стороны входят в одну `GROUP_ID`. Включён во все метрики; доля показана в `intragroup_share_pct`.
- **`payments_count`** — сумма исходного `PAY_CNT`, а не число строк. **`edges_count`** — число уникальных пар `PAYER/BENEFICIARY` после очистки.
- **Временных метрик нет**: в таблице платежей отсутствует дата, поэтому динамика, сезонность и средний интервал между платежами не рассчитываются.

## 5. Очистка данных и допущения

### Компании

- Исходно 85 525 строк, 85 514 уникальных `SYNTHETIC_U`.
- `U_428697` встречается 12 раз с разными `GROUP_ID` и выручкой. Оставлена запись с максимальной `REVENUE_COMPANY`; правило зафиксировано в `meta.company_dataset.dedupe_rule`.

### Платежи

- Исходно 1 380 585 строк.
- Удалены строки, где хотя бы одна сторона отсутствует в справочнике компаний: 991 189 строк.
- Удалены self-loop платежи (`PAYER == BENEFICIARY`): 27 406 строк.
- Повторяющиеся пары `PAYER/BENEFICIARY` агрегированы суммированием `PAY_AMT` и `PAY_CNT`; удалено 5 лишних строк.
- Итог: 361 985 строк в `transactions_clean.csv`.

### Выбор групп

Критерии:

- все компании группы имеют `CL_TYPE = CLIENT`;
- размер группы 1–10 компаний;
- суммарная выручка группы > 15 млрд ₽;
- у каждой компании ≥ 5 транзакционных связей;
- у группы ≥ 50 транзакционных связей;
- максимизируется число различных разделов ОКВЭД, затем регионов, затем классов ОКВЭД; при равенстве — больше транзакций и выручки.

Выбранные группы:

| Ранг | `GROUP_ID` | Компаний | Выручка, млрд ₽ | Связей | Мин. связей у компании | Раздел ОКВЭД | Регион |
|---:|---|---:|---:|---:|---:|---|---|
| 1 | `group_132767_sb` | 8 | 29.48 | 1612 | 166 | G — торговля | Воронежская область |
| 2 | `group_133846_sb` | 3 | 17.84 | 787 | 167 | H — транспортировка и хранение | Москва |
| 3 | `group_134232_sb` | 1 | 16.95 | 61 | 61 | L — операции с недвижимостью | Московская область |

У группы `group_133846_sb` смешанный состав: две компании — транспорт/складская деятельность (ОКВЭД 52), одна — оптовая торговля бытовыми электротоварами (ОКВЭД 46). Преобладающий по выручке раздел — H.

## 6. Пример

Ниже приведён сокращённый пример: массивы `top_3`, `top_okved`, `top_regions` и `top_cities` усечены.

```json
{
  "company_id": "U_128194",
  "main": {
    "okved": {
      "code": "45.31.1",
      "name": "Торговля оптовая автомобильными деталями, узлами и принадлежностями, кроме деятельности агентов",
      "section": { "code": "G", "name": "Торговля оптовая и розничная; ремонт автотранспортных средств и мотоциклов" }
    },
    "bank_services": {
      "cash_settlement_rko": true,
      "bank_guarantees": false,
      "loans": true,
      "leasing": false,
      "deposits": false,
      "salary_project": true,
      "factoring": false
    },
    "location": { "city": "г. Воронеж", "region": "Воронежская область" },
    "ownership_form": "ЧАСТНАЯ СОБСТВЕННОСТЬ",
    "annual_revenue_rub": 7282655891,
    "annual_revenue_bn_rub": 7.28,
    "foreign_trade_countries": [],
    "business_stage": "Оптимизация",
    "client_type": "CLIENT",
    "group_id": "group_132767_sb"
  },
  "payments": {
    "totals": {
      "incoming_amount_rub": 3468710000,
      "outgoing_amount_rub": 2009570000,
      "turnover_rub": 5478280000,
      "incoming_payments_count": 2060,
      "outgoing_payments_count": 11502,
      "edges_count": 213,
      "unique_counterparties_count": 203,
      "external_counterparties_count": 198,
      "intragroup_counterparties_count": 5,
      "intragroup_amount_rub": 491492000,
      "intragroup_share_pct": 8.97,
      "average_edge_amount_rub": 25719624
    },
    "counterparties": {
      "unique_count": 203,
      "top_1_share_pct": 35.66,
      "top_3_share_pct": 54.27,
      "hhi": 1554.05,
      "top_3": [
        {
          "company_id": "U_118748",
          "okved_code": "45.31.1",
          "okved_name": "Торговля оптовая автомобильными деталями, узлами и принадлежностями, кроме деятельности агентов",
          "region": "Москва",
          "city": "г. Москва",
          "is_intragroup": false,
          "incoming_amount_rub": 1950525000,
          "outgoing_amount_rub": 3172000,
          "turnover_rub": 1953697000,
          "payments_count": 342,
          "share_pct": 35.66
        }
      ]
    }
  }
}
```
