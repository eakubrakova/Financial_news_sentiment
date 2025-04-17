import os
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
import feedparser
from dateutil import parser
import time
import datetime
import logging
import html_text
import re

from selenium.webdriver.remote.webelement import WebElement

logging.basicConfig(level=logging.INFO, filename="finam_log.log", filemode="w")

FILE_NAME = 'news_2024.csv'

PAGE_LINKS = {
    'Новости компаний': 'https://www.finam.ru/publications/section/companies/date/',
    'Новости и комментарии': 'https://www.finam.ru/publications/section/market/date/',
    'Сценарии и прогнозы': 'https://www.finam.ru/publications/section/forecasts/date/',
    'Новости международных рынков': 'https://www.finam.ru/publications/section/international/date/'
}

# Раздел 'Обзор и идеи' из RSS ленты
RSS_LINKS = {'Обзор и идеи': 'https://www.finam.ru/analytics/rsspoint/'}

TOP_CONTAINER_ID = 'finfin-local-plugin-block-item-publication-list-transformer-NUMBER'
NEWS_CONTAINER_ID = 'finfin-local-plugin-block-item-publication-list-transformer-NUMBER-wrapper'
LOAD_MORE_ID = 'finfin-local-plugin-block-item-publication-list-transformer-NUMBER-load'

driver = webdriver.Chrome()
driver.get('https://google.ru/')


def get_start_date():
    # Если файл с новостями уже сформирован ранее
    if os.path.exists(FILE_NAME):
        df = pd.read_csv(FILE_NAME, sep=';')
        # найдем последнюю дату и прибавим 1 день
        return pd.to_datetime(df['Date']).max() + datetime.timedelta(days=1)
    else:
        # по умолчанию собираем новости с 1 января 2014 года
        return datetime.datetime.strptime('2024-01-01', '%Y-%m-%d')


def test_class(class1: str, class2: str):
    s1 = class1.split()
    s2 = class2.split()
    for c in s1:
        if c not in s2:
            return False
    return True


# Ищет элементы с заданным набором классов
def find_multiclass_elements(parent: WebElement, multiclass: str):
    elements = []
    classes = multiclass.split()

    for cls in classes:
        for elem in parent.find_elements(By.CLASS_NAME, cls):
            class_attr = elem.get_attribute("class")
            if test_class(multiclass, class_attr) and elem not in elements:
                elements.append(elem)

    return elements


# ждать, пока страница полностью загрузится
def wait_page_ready():
    time.sleep(0.2)
    while True:
        ready = driver.execute_script("return document.readyState;")
        if ready == 'complete':
            break
        time.sleep(0.2)


# определяет transformer number для текущей страницы
# это число добавляется этим сайтом ко многим идентификаторам,
# чтобы затруднить скрапинг (при каждой загрузке страницы число меняется,
# даже для одной и той же страницы)
def find_transformer_num():
    wait_page_ready()
    page_source = driver.page_source
    m = re.search(r"finfin-local-plugin-block-item-publication-list-transformer-(\d+)-wrapper", page_source)
    if m:
        return m.group(1)
    return None


# возвращает актуальный идентификатор контейнера новостей
def news_container_id(num):
    return NEWS_CONTAINER_ID.replace('NUMBER', num)


# возвращает актуальный идентификатор кнопки 'Загрузить еще'
def load_more_id(num):
    return LOAD_MORE_ID.replace('NUMBER', num)


def has_more(num):
    top_container = driver.find_element(By.ID, f"finfin-local-plugin-block-item-publication-list-transformer-{num}")
    state_more = top_container.get_attribute("data-state-more")
    return state_more == 1


# нажать кнопку 'Загрузить еще'
def try_click(num):
    script = f"finfin.local.plugin_block_item_publication_list_transformer_{num}.more.load(this)"
    more_button = driver.find_element(By.ID, load_more_id(num))
    while True:
        try:
            time.sleep(0.2)
            # more_button.click()
            driver.execute_script(script)
            more_button = driver.find_element(By.ID, load_more_id(num))
            break
        except:
            continue


def load_news_page(num):
    wait_page_ready()
    more_button = driver.find_element(By.ID, load_more_id(num))
    while more_button.is_displayed():
        try_click(num)
        wait_page_ready()
        more_button = driver.find_element(By.ID, load_more_id(num))
    else:
        logging.debug("Кнопки загрузки нет")


def save_data(news, date_current):
    # Сохранение
    df = pd.DataFrame(news, columns=['Link', 'Date', 'Source', 'Title', 'Description'])
    # Если файл с новостями уже сформирован ранее
    if os.path.exists(FILE_NAME):
        df_previous = pd.read_csv(FILE_NAME, sep=';')
        # объединение двух датасетов
        pd.concat([df_previous, df]).to_csv(FILE_NAME, sep=';', index=False)
    else:
        df.to_csv(FILE_NAME, sep=';', index=False)

    logging.info(f'Сохранено {len(news)} от {date_current.date()}')


def scrap_one_day(date_current: datetime.datetime):
    news = []

    logging.info(f'Дата {date_current}')
    for page_name, page_link in PAGE_LINKS.items():
        logging.info(f'Страница {page_name}')

        current_link = f"{page_link}{date_current.strftime('%Y-%m-%d')}/"

        try:
            driver.back()
            driver.get(current_link)

            transformer_num = find_transformer_num()

            load_news_page(transformer_num)

            top_container = driver.find_element(By.ID, news_container_id(transformer_num))
            news_list = top_container.find_elements(By.CLASS_NAME, 'mb2x')

            for item in news_list:
                link = ""
                source = ""
                title = ""
                desc = ""

                elements = find_multiclass_elements(item, "cl-blue bold font-l")
                if len(elements) > 0:
                    for elem in elements:
                        if elem.tag_name == 'a' and elem.text:
                            title = elem.text
                            link = elem.get_attribute('href')

                elements = find_multiclass_elements(item, "font-xs cl-darkgrey mr05x")
                if len(elements) > 0:
                    source = elements[0].find_element(By.TAG_NAME, 'span').text

                elements = find_multiclass_elements(item, "font-s cl-black")
                if len(elements) > 0:
                    desc = elements[0].text

                news.append([link,
                             date_current.date(),
                             source,
                             title,
                             html_text.extract_text(desc, guess_layout=False)
                             ])
        except BaseException as e:
            logging.warning(f'Ошибка {e}')

    # Чтение новостей (Обзор и идеи) из RSS ленты
    for page_name, page_link in RSS_LINKS.items():
        logging.info(f'Страница {page_name}')

        driver.back()
        driver.get(page_link)
        page_source = driver.page_source

        feed = feedparser.parse(page_source)
        for entry in feed.entries:
            link = entry.link
            source = entry.author
            title = entry.title
            description = html_text.extract_text(entry.summary, guess_layout=False)
            date = parser.parse(entry.published)

            if date == datetime.datetime.fromtimestamp(date_current.timestamp(), tz=date.tzinfo):
                news.append([link,
                             date.date(),
                             source,
                             title,
                             description
                             ])

    save_data(news, date_current)


def scrap_all():
    date_current = get_start_date()
    date_end = datetime.datetime.now()
    while date_current <= date_end:
        scrap_one_day(date_current)
        date_current = date_current + datetime.timedelta(days=1)


if __name__ == "__main__":
    scrap_all()
    driver.quit()
