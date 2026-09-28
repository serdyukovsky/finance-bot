/**
 * Учёт денег — разметка Google Таблицы.
 *
 * Как запустить:
 * 1. Создай новую пустую Google Таблицу.
 * 2. Расширения → Apps Script, удали всё в редакторе и вставь этот код.
 * 3. Сохрани (Ctrl+S). В списке функций вверху выбери setupFinance
 *    (вспомогательные функции скрыты) и нажми «Выполнить».
 * 4. Разреши доступ при первом запуске.
 * 5. Вернись во вкладку с таблицей — появятся 7 листов и сообщение «Готово».
 *
 * Альтернатива: обнови страницу таблицы — появится меню «Учёт» →
 * «Разметить таблицу».
 *
 * Скрипт рассчитан на пустую таблицу: если листы с такими именами уже есть,
 * он остановится и ничего не тронет.
 *
 * onEdit (ниже) — простой триггер: когда вводишь сумму в «Операции» вручную,
 * он сам ставит сегодняшнюю дату и отметку «вручную».
 */

const SH = {
  home: 'Главная',
  ops: 'Операции',
  plan: 'План',
  debt: 'Долги',
  month: 'Месяц',
  acc: 'Счета',
  cat: 'Категории',
};

const TZ = 'Asia/Barnaul';
const MONEY = '#,##0;[Red]-#,##0';
const DATE_FMT = 'dd.mm.yyyy';
const HEADER_BG = '#e8eaed';

function q_(name) { return "'" + name + "'"; }

function setupFinance() {
  const ss = SpreadsheetApp.getActive();
  if (!ss) {
    throw new Error('Скрипт не привязан к таблице. Открой Apps Script из самой таблицы: ' +
      'Расширения → Apps Script, а не через script.google.com.');
  }

  const existing = Object.values(SH).filter(n => ss.getSheetByName(n));
  if (existing.length) {
    throw new Error('Уже есть листы: ' + existing.join(', ') +
      '. Скрипт рассчитан на пустую таблицу — ничего не изменено.');
  }

  // Формулы ниже записаны в en_US-синтаксисе (запятые). В ru_RU они не разбираются
  // (Formula parse error), поэтому размечаем в en_US, а ru_RU ставим в самом конце —
  // уже разобранные формулы Google сам покажет с «;».
  ss.setSpreadsheetLocale('en_US');
  ss.setSpreadsheetTimeZone(TZ);

  const oldSheets = ss.getSheets();
  const order = [SH.home, SH.ops, SH.plan, SH.debt, SH.month, SH.acc, SH.cat];
  order.forEach((name, i) => ss.insertSheet(name, i));

  // Удаляем только пустые стандартные листы («Лист1»), чужие данные не трогаем
  oldSheets.forEach(s => {
    if (s.getLastRow() === 0 && s.getLastColumn() === 0) ss.deleteSheet(s);
  });

  buildAccounts_(ss);
  buildCategories_(ss);
  buildOps_(ss);
  buildPlan_(ss);
  buildHome_(ss);
  buildDebts_(ss);
  buildMonth_(ss);

  // Цвета вкладок: ввод — зелёный, просмотр — синий, настройки — серый
  [SH.ops, SH.plan].forEach(n => ss.getSheetByName(n).setTabColor('#34a853'));
  [SH.home, SH.debt, SH.month].forEach(n => ss.getSheetByName(n).setTabColor('#4285f4'));
  [SH.acc, SH.cat].forEach(n => ss.getSheetByName(n).setTabColor('#9aa0a6'));

  SpreadsheetApp.flush();
  ss.setSpreadsheetLocale('ru_RU');
  ss.setActiveSheet(ss.getSheetByName(SH.home));
  SpreadsheetApp.flush();
  ss.toast('Все 7 листов созданы', 'Готово', 10);
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Учёт')
    .addItem('Разметить таблицу', 'setupFinance')
    .addToUi();
}

/* ---------- helpers ---------- */

function styleHeader_(sh, cols) {
  sh.getRange(1, 1, 1, cols)
    .setFontWeight('bold')
    .setBackground(HEADER_BG);
  sh.setFrozenRows(1);
}

function listRule_(values) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInList(values, true)
    .setAllowInvalid(false)
    .build();
}

function rangeRule_(range) {
  return SpreadsheetApp.newDataValidation()
    .requireValueInRange(range, true)
    .setAllowInvalid(false)
    .build();
}

function dateRule_() {
  return SpreadsheetApp.newDataValidation()
    .requireDate()
    .setAllowInvalid(false)
    .build();
}

function todayNoon_() {
  const [y, m, d] = Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd')
    .split('-').map(Number);
  return new Date(y, m - 1, d, 12);
}

/* ---------- Счета ---------- */

function buildAccounts_(ss) {
  const sh = ss.getSheetByName(SH.acc);
  const t = todayNoon_();

  sh.getRange('A1:I1').setValues([[
    'Счёт', 'Тип', 'Ключ для бота', 'Ставка', 'Мин. платёж',
    'День платежа', 'День выписки', 'Начальный остаток', 'Дата остатка',
  ]]);
  sh.getRange('K1').setValue('Дата сверки');

  // Баланс = начальный остаток + операции по счёту + входящие переводы
  sh.getRange('J1').setFormula(
    '={"Баланс";MAP(A2:A,H2:H,LAMBDA(a,h,IF(a="","",' +
    'h+SUMIFS(' + q_(SH.ops) + '!B:B,' + q_(SH.ops) + '!C:C,a)' +
    '-SUMIFS(' + q_(SH.ops) + '!B:B,' + q_(SH.ops) + '!D:D,a))))}'
  );
  styleHeader_(sh, 11);

  sh.getRange('A2:I6').setValues([
    ['Карта',          'обычный',  'карта',  '',     '',    '', '', 0,       t],
    ['Наличные',       'обычный',  'нал',    '',     '',    '', '', 0,       t],
    ['Кредитка Альфа', 'кредитка', 'альфа',  0.5849, '',    '', 26, -74781,  t],
    ['Кредитка Сбер',  'кредитка', 'сбер',   0.36,   10545, 5,  '', -216249, t],
    ['Кредит',         'кредит',   'кредит', 0.2367, 4083,  27, '', -82761,  t],
  ]);

  sh.getRange('B2:B100').setDataValidation(listRule_(['обычный', 'кредитка', 'кредит', 'долг']));
  sh.getRange('D2:D100').setNumberFormat('0.00%');
  sh.getRange('E2:E100').setNumberFormat(MONEY);
  sh.getRange('H2:H100').setNumberFormat(MONEY);
  sh.getRange('J2:J100').setNumberFormat(MONEY);
  sh.getRange('I2:I100').setNumberFormat(DATE_FMT);
  sh.getRange('K2:K100').setNumberFormat(DATE_FMT);
  sh.getRange('J1:J100').setBackground('#f1f3f4');
  sh.getRange('J1').setBackground(HEADER_BG);

  sh.setColumnWidth(1, 150);
  sh.setColumnWidths(2, 10, 110);
}

/* ---------- Категории ---------- */

function buildCategories_(ss) {
  const sh = ss.getSheetByName(SH.cat);
  sh.getRange('A1:D1').setValues([['Категория', 'Тип', 'Обязательная', 'Ключевые слова']]);
  styleHeader_(sh, 4);

  const rows = [
    // расходы
    ['Продукты',            'расход', true,  'магнит, пятёрочка, мария-ра, ярче, продукты'],
    ['Кафе и доставка',     'расход', false, 'кафе, кофе, шаурма, доставка, яндекс еда'],
    ['Транспорт',           'расход', true,  'такси, автобус, проезд, бензин'],
    ['Жильё',               'расход', true,  'аренда, квартира, коммуналка, свет'],
    ['Связь',               'расход', true,  'мтс, телефон, интернет'],
    ['Рабочие инструменты', 'расход', false, 'claude, cursor, хостинг, домен, api'],
    ['Подписки',            'расход', false, 'подписка, музыка, кино, suno'],
    ['Кот',                 'расход', true,  'корм, наполнитель, вет, кот'],
    ['Здоровье',            'расход', true,  'аптека, врач, лекарства'],
    ['Дом и одежда',        'расход', false, 'одежда, хозтовары, быт'],
    ['Техника',             'расход', false, 'ноут, наушники, термопаста'],
    ['Досуг',               'расход', false, 'подарок, кино, бар'],
    ['Проценты и комиссии', 'расход', true,  'проценты, комиссия'],
    ['Прочее',              'расход', false, ''],
    // доходы
    ['Зарплата',            'доход',  false, 'зп, зарплата, аванс, оклад'],
    ['Процент',             'доход',  false, 'процент, премия, бонус'],
    ['Фриланс',             'доход',  false, 'лендинг, заказ, фриланс, сайт'],
    ['event-calendar',      'доход',  false, 'event, ивент, календарь'],
    ['Барабаны',            'доход',  false, 'барабаны, урок'],
    ['Прочий доход',        'доход',  false, 'возврат, продал, кэшбэк'],
    // служебные
    ['Перевод',             'служебная', false, ''],
    ['Корректировка',       'служебная', false, 'корректировка, сверка'],
  ];

  sh.getRange('C2:C100').insertCheckboxes();
  sh.getRange(2, 1, rows.length, 4).setValues(rows);
  sh.getRange('B2:B100').setDataValidation(listRule_(['расход', 'доход', 'служебная']));

  sh.setColumnWidth(1, 170);
  sh.setColumnWidth(2, 100);
  sh.setColumnWidth(3, 110);
  sh.setColumnWidth(4, 360);
}

/* ---------- Операции ---------- */

function buildOps_(ss) {
  const sh = ss.getSheetByName(SH.ops);
  const accRange = ss.getSheetByName(SH.acc).getRange('A2:A100');
  const catRange = ss.getSheetByName(SH.cat).getRange('A2:A100');

  sh.getRange('A1:G1').setValues([[
    'Дата', 'Сумма', 'Счёт', 'Куда', 'Категория', 'Комментарий', 'Источник',
  ]]);
  sh.getRange('H1').setFormula(
    '={"Месяц";ARRAYFORMULA(IF(A2:A="","",YEAR(A2:A)&"-"&TEXT(MONTH(A2:A),"00")))}'
  );
  styleHeader_(sh, 8);

  const n = sh.getMaxRows() - 1;
  sh.getRange(2, 1, n, 1).setDataValidation(dateRule_()).setNumberFormat(DATE_FMT);
  sh.getRange(2, 2, n, 1).setNumberFormat(MONEY);
  sh.getRange(2, 3, n, 1).setDataValidation(rangeRule_(accRange));
  sh.getRange(2, 4, n, 1).setDataValidation(rangeRule_(accRange));
  sh.getRange(2, 5, n, 1).setDataValidation(rangeRule_(catRange));
  sh.getRange(2, 7, n, 1).setDataValidation(listRule_(['вручную', 'бот']));
  sh.getRange(1, 8, n + 1, 1).setBackground('#f1f3f4');
  sh.getRange('H1').setBackground(HEADER_BG);

  sh.setColumnWidth(1, 95);
  sh.setColumnWidth(2, 100);
  sh.setColumnWidths(3, 2, 140);
  sh.setColumnWidth(5, 170);
  sh.setColumnWidth(6, 240);
  sh.setColumnWidths(7, 2, 85);
}

/* ---------- План ---------- */

function buildPlan_(ss) {
  const sh = ss.getSheetByName(SH.plan);
  const accRange = ss.getSheetByName(SH.acc).getRange('A2:A100');

  sh.getRange('A1:G1').setValues([[
    'Название', 'Сумма', 'Повтор', 'День месяца', 'Дата (разово)', 'Счёт', 'Статус',
  ]]);
  // Ближайшая дата: для ежемесячных — ближайшее такое число, для разовых — дата,
  // пока статус не «пришло»/«оплачено»
  sh.getRange('H1').setFormula(
    '={"Ближайшая дата";ARRAYFORMULA(IF(A2:A="","",' +
    'IF(C2:C="ежемесячно",' +
      'IF(D2:D="","",IF(DAY(TODAY())<=D2:D,' +
        'DATE(YEAR(TODAY()),MONTH(TODAY()),D2:D),' +
        'DATE(YEAR(TODAY()),MONTH(TODAY())+1,D2:D))),' +
      'IF((G2:G="пришло")+(G2:G="оплачено"),"",E2:E))))}'
  );
  styleHeader_(sh, 8);

  sh.getRange('A2:A4').setValues([
    ['Кредитка Сбер — платёж'],
    ['Кредит — платёж'],
    ['Кредитка Альфа — мин. платёж'],
  ]);
  // Суммы платежей по долгам берутся из «Счетов», чтобы не дублировать
  sh.getRange('B2:B4').setFormulas([
    ['=-' + q_(SH.acc) + '!E5'],
    ['=-' + q_(SH.acc) + '!E6'],
    ['=-' + q_(SH.acc) + '!E4'],
  ]);
  sh.getRange('C2:D4').setValues([
    ['ежемесячно', 5],
    ['ежемесячно', 27],
    ['ежемесячно', ''],
  ]);
  sh.getRange('F2:F4').setValues([['Карта'], ['Карта'], ['Карта']]);
  sh.getRange('D4').setNote('Укажи день, до которого нужно внести минимальный платёж по Альфе');

  sh.getRange('B2:B200').setNumberFormat(MONEY);
  sh.getRange('C2:C200').setDataValidation(listRule_(['ежемесячно', 'разово']));
  sh.getRange('E2:E200').setDataValidation(dateRule_()).setNumberFormat(DATE_FMT);
  sh.getRange('F2:F200').setDataValidation(rangeRule_(accRange));
  sh.getRange('G2:G200').setDataValidation(listRule_(['ждём', 'пришло', 'оплачено']));
  sh.getRange('H2:H200').setNumberFormat(DATE_FMT).setBackground('#f1f3f4');

  sh.setColumnWidth(1, 230);
  sh.setColumnWidths(2, 7, 115);
}

/* ---------- Главная ---------- */

function buildHome_(ss) {
  const sh = ss.getSheetByName(SH.home);
  const A = q_(SH.acc), P = q_(SH.plan), D = q_(SH.debt);

  sh.getRange('A1').setValue('Главная').setFontSize(16).setFontWeight('bold');

  sh.getRange('A3').setValue('Настройки').setFontWeight('bold');
  sh.getRange('A4:B5').setValues([
    ['День зарплаты (самый поздний)', 8],
    ['День аванса (самый поздний)', 25],
  ]);
  sh.getRange('B4:B5').setBackground('#fef7e0');

  sh.getRange('A7').setValue('Сейчас').setFontWeight('bold');
  const nextPay = (cell) =>
    'IF(DAY(TODAY())<' + cell + ',DATE(YEAR(TODAY()),MONTH(TODAY()),' + cell + '),' +
    'DATE(YEAR(TODAY()),MONTH(TODAY())+1,' + cell + '))';

  const rows = [
    ['Свободные деньги',
      '=SUMIFS(' + A + '!J2:J,' + A + '!B2:B,"обычный")'],
    ['Следующее поступление',
      '=MIN(' + nextPay('B4') + ',' + nextPay('B5') + ')'],
    ['Дней до него',
      '=B9-TODAY()'],
    ['Обязательные платежи до него',
      '=-SUMIFS(' + P + '!B2:B,' + P + '!H2:H,">="&TODAY(),' + P + '!H2:H,"<"&B9,' + P + '!B2:B,"<0")'],
    ['Можно тратить в день',
      '=ROUND((B8-B11)/B10,0)'],
    ['Чистый капитал',
      '=SUM(' + A + '!J2:J)'],
    ['Общий долг',
      '=-SUMIFS(' + A + '!J2:J,' + A + '!B2:B,"кредитка")-SUMIFS(' + A + '!J2:J,' + A + '!B2:B,"кредит")'],
    ['Проценты в месяц (оценка)',
      '=' + D + '!D15'],
  ];
  rows.forEach((r, i) => {
    sh.getRange(8 + i, 1).setValue(r[0]);
    sh.getRange(8 + i, 2).setFormula(r[1]);
  });
  sh.getRange('B8:B15').setNumberFormat(MONEY);
  sh.getRange('B9').setNumberFormat(DATE_FMT);
  sh.getRange('B10').setNumberFormat('0');
  sh.getRange('A12:B12').setFontWeight('bold').setBackground('#e6f4ea');

  sh.getRange('D3').setValue('Ближайшие платежи (14 дней)').setFontWeight('bold');
  sh.getRange('D4:F4').setValues([['Дата', 'Что', 'Сумма']])
    .setFontWeight('bold').setBackground(HEADER_BG);
  sh.getRange('D5').setFormula(
    '=IFERROR(SORT(FILTER({' + P + '!H2:H,' + P + '!A2:A,' + P + '!B2:B},' +
    P + '!H2:H<>"",' + P + '!H2:H>=TODAY(),' + P + '!H2:H<=TODAY()+14),1,TRUE),"ничего")'
  );
  sh.getRange('D5:D30').setNumberFormat(DATE_FMT);
  sh.getRange('F5:F30').setNumberFormat(MONEY);

  sh.setColumnWidth(1, 240);
  sh.setColumnWidth(2, 120);
  sh.setColumnWidth(3, 30);
  sh.setColumnWidth(4, 95);
  sh.setColumnWidth(5, 230);
  sh.setColumnWidth(6, 110);
}

/* ---------- Долги ---------- */

function buildDebts_(ss) {
  const sh = ss.getSheetByName(SH.debt);
  const A = q_(SH.acc), O = q_(SH.ops);
  const R = (col) => col + '4:' + col + '13';

  sh.getRange('A1:B1').setValues([['Доп. платёж в месяц (сценарий)', 5000]]);
  sh.getRange('B1').setBackground('#fef7e0').setNumberFormat(MONEY);

  sh.getRange('A3:J3').setValues([[
    'Долг', 'Остаток', 'Ставка', 'Проценты/мес', 'Платёж', 'В тело',
    'Месяцев до нуля', 'Переплата ≈', 'Месяцев с доп.', 'Быстрее на, мес',
  ]]).setFontWeight('bold').setBackground(HEADER_BG);

  sh.getRange('A4').setFormula(
    '=FILTER(' + A + '!A2:A,(' + A + '!B2:B="кредитка")+(' + A + '!B2:B="кредит"))'
  );
  sh.getRange('B4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",-IFERROR(VLOOKUP(' + R('A') +
    ',{' + A + '!A2:A,' + A + '!J2:J},2,FALSE))))'
  );
  sh.getRange('C4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",VLOOKUP(' + R('A') + ',' + A + '!A2:D,4,FALSE)))'
  );
  sh.getRange('D4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",ROUND(' + R('B') + '*' + R('C') + '/12,0)))'
  );
  sh.getRange('E4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",VLOOKUP(' + R('A') + ',' + A + '!A2:E,5,FALSE)))'
  );
  sh.getRange('F4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",' + R('E') + '-' + R('D') + '))'
  );
  sh.getRange('G4').setFormula(
    '=ARRAYFORMULA(IF(' + R('A') + '="","",' +
    'IF(' + R('B') + '<=0,"закрыт",' +
    'IF((' + R('E') + '="")+(' + R('E') + '=0),"укажи платёж",' +
    'IF(' + R('F') + '<=0,"не гасится",' +
    'ROUNDUP(NPER(' + R('C') + '/12,-' + R('E') + ',' + R('B') + '),0))))))'
  );
  sh.getRange('H4').setFormula(
    '=ARRAYFORMULA(IF(ISNUMBER(' + R('G') + '),ROUND(' + R('E') + '*' + R('G') + '-' + R('B') + ',0),""))'
  );
  sh.getRange('I4').setFormula(
    '=ARRAYFORMULA(IF(ISNUMBER(' + R('G') + '),ROUNDUP(NPER(' + R('C') + '/12,-(' + R('E') +
    '+$B$1),' + R('B') + '),0),""))'
  );
  sh.getRange('J4').setFormula(
    '=ARRAYFORMULA(IF(ISNUMBER(' + R('I') + '),' + R('G') + '-' + R('I') + ',""))'
  );

  sh.getRange('A15').setValue('Итого').setFontWeight('bold');
  sh.getRange('B15').setFormula('=SUM(B4:B13)');
  sh.getRange('D15').setFormula('=SUM(D4:D13)');
  sh.getRange('E15').setFormula('=SUM(E4:E13)');
  sh.getRange('F15').setFormula('=E15-D15');
  sh.getRange('A15:J15').setFontWeight('bold').setBackground('#f1f3f4');

  sh.getRange('A17').setValue('Гасить сверх минимума →').setFontWeight('bold');
  sh.getRange('B17').setFormula(
    '=IFERROR(INDEX(SORT(FILTER({A4:A13,C4:C13},A4:A13<>"",B4:B13>0),2,FALSE),1,1),"—")'
  ).setFontWeight('bold').setBackground('#fce8e6');

  sh.getRange('A18').setValue('Уплачено процентов с начала учёта');
  sh.getRange('B18').setFormula(
    '=-SUMIFS(' + O + '!B2:B,' + O + '!E2:E,"Проценты и комиссии")'
  ).setNumberFormat(MONEY);

  sh.getRange('A20').setValue('Долги с людьми (плюс — должны мне)').setFontWeight('bold');
  sh.getRange('A21').setFormula(
    '=IFERROR(FILTER({' + A + '!A2:A,' + A + '!J2:J},' + A + '!B2:B="долг"),"нет")'
  );

  ['B', 'D', 'E', 'F', 'H'].forEach(c => sh.getRange(c + '4:' + c + '15').setNumberFormat(MONEY));
  sh.getRange('C4:C13').setNumberFormat('0.00%');
  sh.getRange('B21:B40').setNumberFormat(MONEY);

  sh.setColumnWidth(1, 250);
  sh.setColumnWidths(2, 9, 115);
}

/* ---------- Месяц ---------- */

function buildMonth_(ss) {
  const sh = ss.getSheetByName(SH.month);
  const O = q_(SH.ops), C = q_(SH.cat), A = q_(SH.acc);

  sh.getRange('A1').setValue('Месяц (гггг-мм)').setFontWeight('bold');
  sh.getRange('B1').setNumberFormat('@')
    .setValue(Utilities.formatDate(new Date(), TZ, 'yyyy-MM'))
    .setBackground('#fef7e0');

  sh.getRange('A3:B3').setValues([['Доход', 'Сумма']]);
  sh.getRange('D3:F3').setValues([['Расход', 'Сумма', 'Тип']]);
  sh.getRange('H3:I3').setValues([['Итоги', '']]);
  sh.getRange('A3:I3').setFontWeight('bold');
  [sh.getRange('A3:B3'), sh.getRange('D3:F3'), sh.getRange('H3:I3')]
    .forEach(r => r.setBackground(HEADER_BG));

  sh.getRange('A4').setFormula('=FILTER(' + C + '!A2:A,' + C + '!B2:B="доход")');
  sh.getRange('B4').setFormula(
    '=MAP(A4:A20,LAMBDA(c,IF(c="","",SUMIFS(' + O + '!B:B,' + O + '!E:E,c,' + O + '!H:H,$B$1))))'
  );

  sh.getRange('D4').setFormula('=FILTER(' + C + '!A2:A,' + C + '!B2:B="расход")');
  sh.getRange('E4').setFormula(
    '=MAP(D4:D40,LAMBDA(c,IF(c="","",-SUMIFS(' + O + '!B:B,' + O + '!E:E,c,' + O + '!H:H,$B$1))))'
  );
  sh.getRange('F4').setFormula(
    '=MAP(D4:D40,LAMBDA(c,IF(c="","",IF(VLOOKUP(c,' + C + '!A:C,3,FALSE),"обяз.",""))))'
  );

  const debtList = 'FILTER(' + A + '!A2:A,(' + A + '!B2:B="кредитка")+(' + A + '!B2:B="кредит"))';
  const totals = [
    ['Доходы', '=SUM(B4:B20)'],
    ['Расходы', '=SUM(E4:E40)'],
    ['  обязательные', '=SUMIFS(E4:E40,F4:F40,"обяз.")'],
    ['  необязательные', '=I5-I6'],
    ['Проценты банкам', '=-SUMIFS(' + O + '!B2:B,' + O + '!E2:E,"Проценты и комиссии",' + O + '!H2:H,$B$1)'],
    ['Внесено в долги',
      '=-SUMPRODUCT((' + O + '!H2:H=$B$1)*ISNUMBER(MATCH(' + O + '!D2:D,' + debtList + ',0))*' + O + '!B2:B)'],
    ['  из них в тело ≈', '=I9-I8'],
    ['Итог месяца (доходы − расходы)', '=I4-I5'],
  ];
  totals.forEach((r, i) => {
    sh.getRange(4 + i, 8).setValue(r[0]);
    sh.getRange(4 + i, 9).setFormula(r[1]);
  });
  sh.getRange('H11:I11').setFontWeight('bold').setBackground('#e6f4ea');

  sh.getRange('B4:B20').setNumberFormat(MONEY);
  sh.getRange('E4:E40').setNumberFormat(MONEY);
  sh.getRange('I4:I11').setNumberFormat(MONEY);

  sh.setColumnWidth(1, 150);
  sh.setColumnWidth(2, 100);
  sh.setColumnWidth(3, 30);
  sh.setColumnWidth(4, 170);
  sh.setColumnWidths(5, 2, 90);
  sh.setColumnWidth(7, 30);
  sh.setColumnWidth(8, 230);
  sh.setColumnWidth(9, 110);
}

/* ---------- автодата при ручном вводе ---------- */

function onEdit(e) {
  if (!e || !e.range) return;
  const sh = e.range.getSheet();
  if (sh.getName() !== SH.ops) return;
  if (e.range.getNumRows() !== 1 || e.range.getColumn() !== 2) return;
  const row = e.range.getRow();
  if (row < 2 || e.range.getValue() === '') return;

  const dateCell = sh.getRange(row, 1);
  if (!dateCell.getValue()) dateCell.setValue(todayNoon_());

  const srcCell = sh.getRange(row, 7);
  if (!srcCell.getValue()) srcCell.setValue('вручную');
}
