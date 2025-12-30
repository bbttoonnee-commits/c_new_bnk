#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generator kanału RSS dla Bankier.pl/wiadomosc
Optimized for GitHub Actions & automation
"""

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from datetime import datetime, timedelta
import pytz
import time
import sys
from urllib.parse import urljoin

# ============================================================================
# KONFIGURACJA
# ============================================================================

BASE_URL = "https://www.bankier.pl"
NEWS_URL = f"{BASE_URL}/wiadomosc/"
PAGES_TO_SCAN = 5  # Liczba stron do przeskanowania
TIME_FILTER_HOURS = 48  # Artykuły z ostatnich 48h
OUTPUT_FILE = "bankier_rss.xml"
REQUEST_DELAY = 2  # Sekundy między requestami (anti-bot)

# Nagłówki HTTP imitujące przeglądarkę
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.bankier.pl/',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Cache-Control': 'max-age=0',
}

# ============================================================================
# FUNKCJE POMOCNICZE
# ============================================================================

def get_page_url(page_number):
    """Generuje URL dla danej strony"""
    if page_number == 1:
        return NEWS_URL
    return f"{NEWS_URL}{page_number}/"


def fetch_page(url, retry=3):
    """Pobiera stronę z obsługą błędów i retry"""
    for attempt in range(retry):
        try:
            print(f"  → Pobieranie: {url} (próba {attempt + 1}/{retry})")
            response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            response.raise_for_status()
            # POPRAWKA: Wymuszamy UTF-8
            response.encoding = 'utf-8'
            print(f"  ✓ Sukces: {response.status_code} ({len(response.content)} bajtów)")
            return response
        except requests.RequestException as e:
            print(f"  ✗ Błąd: {e}")
            if attempt < retry - 1:
                wait_time = (attempt + 1) * 2
                print(f"  ⏳ Ponowna próba za {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"  ✗ Nie udało się pobrać strony po {retry} próbach")
                return None


def parse_datetime(datetime_str):
    """Parsuje datę w formacie ISO 8601 z timezone"""
    try:
        # Format: 2025-12-30T11:44:00+01:00
        dt = datetime.fromisoformat(datetime_str)
        # Upewniamy się, że ma timezone
        if dt.tzinfo is None:
            dt = pytz.timezone('Europe/Warsaw').localize(dt)
        return dt
    except Exception as e:
        print(f"  ⚠ Błąd parsowania daty '{datetime_str}': {e}")
        return None


def is_recent(article_date, hours=TIME_FILTER_HOURS):
    """Sprawdza czy artykuł jest z ostatnich X godzin"""
    if article_date is None:
        return False
    now = datetime.now(pytz.timezone('Europe/Warsaw'))
    cutoff = now - timedelta(hours=hours)
    return article_date >= cutoff


def extract_articles_from_page(soup, page_num):
    """Wyciąga artykuły z pojedynczej strony"""
    articles = []
    
    # Szukamy divów z klasą "article"
    article_divs = soup.find_all('div', class_='article')
    
    print(f"  📄 Znaleziono {len(article_divs)} kontenerów <div class='article'> na stronie {page_num}")
    
    for idx, article_div in enumerate(article_divs, 1):
        try:
            # POPRAWKA: Tytuł jest w <span class="entry-title"> -> <a>
            title_span = article_div.find('span', class_='entry-title')
            
            if not title_span:
                print(f"    ⚠ [{idx}] Brak <span class='entry-title'> - pomijam")
                continue
            
            title_link = title_span.find('a')
            
            if not title_link or not title_link.get('href'):
                print(f"    ⚠ [{idx}] Brak linku w entry-title - pomijam")
                continue
            
            if not title_link or not title_link.get('href'):
                print(f"    ⚠ [{idx}] Brak linku w entry-title - pomijam")
                continue
            
            title = title_link.get_text(strip=True)
            link = title_link.get('href')
            
            # Budujemy pełny URL
            if not link.startswith('http'):
                link = urljoin(BASE_URL, link)
            
            # Pomijamy linki zewnętrzne/nieprawidłowe
            if not link.startswith(BASE_URL):
                print(f"    ⚠ [{idx}] Link zewnętrzny - pomijam: {link}")
                continue
            
            # Wyciągamy datę z <time class="entry-date"> (PIERWSZY tag time)
            entry_meta = article_div.find('div', class_='entry-meta')
            time_tag = None
            
            if entry_meta:
                time_tag = entry_meta.find('time', class_='entry-date')
            
            # Fallback - szukamy bezpośrednio w article_div
            if not time_tag:
                time_tag = article_div.find('time', class_='entry-date')
            
            if not time_tag or not time_tag.get('datetime'):
                print(f"    ⚠ [{idx}] Brak daty - pomijam: {title[:50]}...")
                continue
            
            pub_date = parse_datetime(time_tag['datetime'])
            if not pub_date:
                continue
            
            # Filtr czasowy
            if not is_recent(pub_date):
                print(f"    ⏭ [{idx}] Za stary artykuł ({pub_date.strftime('%Y-%m-%d %H:%M')}) - pomijam")
                continue
            
            # Wyciągamy opis z <p> (pierwszy akapit po entry-title)
            description = ""
            # Szukamy <p> w entry-content (pomijamy linki "Czytaj dalej")
            entry_content = article_div.find('div', class_='entry-content')
            if entry_content:
                p_tag = entry_content.find('p')
                if p_tag:
                    # Usuwamy link "Czytaj dalej"
                    more_link = p_tag.find('a', class_='more-link')
                    if more_link:
                        more_link.decompose()
                    description = p_tag.get_text(strip=True)
            
            article = {
                'title': title,
                'link': link,
                'description': description or title,  # Fallback do tytułu
                'pub_date': pub_date,
                'guid': link,  # Unikalny identyfikator
            }
            
            articles.append(article)
            print(f"    ✓ [{idx}] {title[:60]}... ({pub_date.strftime('%Y-%m-%d %H:%M')})")
            
        except Exception as e:
            print(f"    ✗ [{idx}] Błąd parsowania artykułu: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    return articles


def remove_duplicates(articles):
    """Usuwa duplikaty na podstawie linku (GUID)"""
    seen = set()
    unique = []
    
    for article in articles:
        if article['guid'] not in seen:
            seen.add(article['guid'])
            unique.append(article)
    
    removed = len(articles) - len(unique)
    if removed > 0:
        print(f"\n🔄 Usunięto {removed} duplikatów")
    
    return unique


def generate_rss_feed(articles, output_file=OUTPUT_FILE):
    """Generuje plik RSS z artykułami"""
    print(f"\n📝 Generowanie RSS...")
    
    # Inicjalizacja feed generatora
    fg = FeedGenerator()
    fg.id(NEWS_URL)
    fg.title('Bankier.pl - Wiadomości')
    fg.author({'name': 'Bankier.pl', 'email': 'redakcja@bankier.pl'})
    fg.link(href=NEWS_URL, rel='alternate')
    fg.description('Najnowsze wiadomości z serwisu Bankier.pl')
    fg.language('pl')
    fg.updated(datetime.now(pytz.timezone('Europe/Warsaw')))
    
    # Sortujemy artykuły od najnowszych
    articles_sorted = sorted(articles, key=lambda x: x['pub_date'], reverse=True)
    
    # Dodajemy artykuły do feedu
    for article in articles_sorted:
        fe = fg.add_entry()
        fe.id(article['guid'])
        fe.title(article['title'])
        fe.link(href=article['link'])
        fe.description(article['description'])
        fe.published(article['pub_date'])
        fe.updated(article['pub_date'])
    
    # Zapisujemy do pliku
    fg.rss_file(output_file, pretty=True)
    print(f"✓ Zapisano do pliku: {output_file}")
    print(f"✓ Liczba artykułów w RSS: {len(articles_sorted)}")


# ============================================================================
# GŁÓWNA LOGIKA
# ============================================================================

def main():
    """Główna funkcja programu"""
    print("=" * 70)
    print("🚀 BANKIER.PL RSS GENERATOR")
    print("=" * 70)
    print(f"📅 Filtr czasowy: ostatnie {TIME_FILTER_HOURS}h")
    print(f"📄 Stron do przeskanowania: {PAGES_TO_SCAN}")
    print(f"⏱️  Opóźnienie między requestami: {REQUEST_DELAY}s")
    print("=" * 70)
    
    all_articles = []
    
    # Pętla po stronach
    for page_num in range(1, PAGES_TO_SCAN + 1):
        print(f"\n📖 Strona {page_num}/{PAGES_TO_SCAN}")
        print("-" * 70)
        
        url = get_page_url(page_num)
        response = fetch_page(url)
        
        if response is None:
            print(f"  ⚠ Pomijam stronę {page_num} z powodu błędu")
            continue
        
        soup = BeautifulSoup(response.content, 'html.parser')
        articles = extract_articles_from_page(soup, page_num)
        all_articles.extend(articles)
        
        print(f"  ✓ Zebrano {len(articles)} artykułów ze strony {page_num}")
        
        # Opóźnienie przed kolejnym requestem (anti-bot)
        if page_num < PAGES_TO_SCAN:
            print(f"  ⏳ Czekam {REQUEST_DELAY}s przed kolejną stroną...")
            time.sleep(REQUEST_DELAY)
    
    # Podsumowanie
    print("\n" + "=" * 70)
    print(f"📊 PODSUMOWANIE")
    print("=" * 70)
    print(f"Zebrano łącznie: {len(all_articles)} artykułów")
    
    if not all_articles:
        print("⚠ Nie znaleziono żadnych artykułów! Sprawdź konfigurację.")
        print("\n💡 DEBUGOWANIE - zapisuję pierwszą stronę do pliku debug.html")
        try:
            response = requests.get(NEWS_URL, headers=HEADERS, timeout=10)
            with open('debug.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            print("✓ Zapisano debug.html - sprawdź ten plik aby zobaczyć strukturę HTML")
        except Exception as e:
            print(f"✗ Nie udało się zapisać debug.html: {e}")
        return 1
    
    # Usuwanie duplikatów
    unique_articles = remove_duplicates(all_articles)
    print(f"Po deduplikacji: {len(unique_articles)} unikalnych artykułów")
    
    # Generowanie RSS
    generate_rss_feed(unique_articles)
    
    print("\n" + "=" * 70)
    print("✅ ZAKOŃCZONO POMYŚLNIE")
    print("=" * 70)
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠ Przerwano przez użytkownika")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ KRYTYCZNY BŁĄD: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
