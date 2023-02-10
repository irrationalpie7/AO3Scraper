# Retrieve authors from an AO3 people search
# Will return in searched order
# Saves ids and some metadata to a csv for later use

from bs4 import BeautifulSoup
import re
import time
import requests
import csv
import sys
import datetime
import argparse
import os

page_empty = False
url = ""
num_requested_authors = 0
num_recorded_authors = 0
csv_name = ""
continue_csv = False
tags = []

# keep track of all processed ids to avoid repeats:
# this is separate from the temporary batch of ids
# that are written to the csv and then forgotten
seen_ids = set()

# 
# Ask the user for:
# a url of a people search page
# e.g. 
# https://archiveofourown.org/people/search?people_search%5Bquery%5D=&people_search%5Bname%5D=&people_search%5Bfandom%5D=Harry+Potter+-+J.+K.+Rowling&commit=Search+People
# how many authors they want
# what to call the output csv

def get_args():
    global url
    global csv_name
    global num_requested_authors
    global continue_csv

    parser = argparse.ArgumentParser(description='Scrape AO3 authors given a people search URL')
    parser.add_argument(
        'url', metavar='URL',
        help='a single URL pointing to an AO3 search page')
    parser.add_argument(
        '--out_csv', default='author_ids',
        help='csv output file name')
    parser.add_argument(
        '--header', default='',
        help='user http header')
    parser.add_argument(
        '--continue_csv', default='', 
        help='pick up where the csv file left off')
    parser.add_argument(# while testing, default to 20 so you only make a single request
        '--num_to_retrieve', default='20',#'a', 
        help='how many fic ids you want')

    args = parser.parse_args()
    url = args.url
    csv_name = str(args.out_csv)

    continue_csv = str(args.continue_csv)
    if continue_csv != "":
        continue_csv = True
    else:
        continue_csv = False
    
    # defaults to all
    if (str(args.num_to_retrieve) == 'a'):
        num_requested_authors = -1
    else:
        num_requested_authors = int(args.num_to_retrieve)

    header_info = str(args.header)

    return header_info

# 
# navigate to a people search page,
# then extract all authors
# 
def get_ids(header_info=''):
    global page_empty
    global seen_ids

    # make the request. if we 429, try again later 
    headers = {'user-agent' : header_info}
    req = requests.get(url, headers=headers)
    while req.status_code == 429:
        # >5 second delay between requests as per AO3's terms of service
        print("Request answered with Status-Code 429, waiting before retrying...")
        print(f"Info: {url}")
        time.sleep(10)
        req = requests.get(url, headers=headers)

    soup = BeautifulSoup(req.text, "lxml")

    # some responsiveness in the "UI"
    sys.stdout.write('.')
    sys.stdout.flush()
    authors = soup.select("li.user > .header:first-child")
    # see if we've gone too far and run out of authors: 
    if (len(authors) == 0):
        page_empty = True

    # process list for new authors
    ids = []
    for author_blurb in authors:
        # First three columns:
        # author(/pseud), author link, pseud link,
        # <author>/<pseud>, link to author, link to pseud
        # OR
        # <author>, link to author, <blank>

        # Then:
        # # works, link, # bookmarks, link,

        # Then, per fandom:
        # # works, link

        # fandoms:
        # 
        
        # Then:
        # 

        # author/pseud, link       (for sorting)
        # 
        # pseud (author), link
        # author, link
        author = extract_author_info(author_blurb)
        extract_author_metadata(author,author_blurb)
        if not author['id'] in seen_ids:
            ids.append(author)
            seen_ids.add(author['id'])
    return ids

def href(element):
    if element is None:
        return ""
    url = element['href']
    if url.startswith("http"):
        return url
    return "https://archiveofourown.org" + url

def extract_author_info(author_blurb):
    a_s = author_blurb.select('h4 a')
    author_a = None
    pseud_a = None
    for a in a_s:
        if "/pseuds/" in a['href']:
            pseud_a = a
        else:
            author_a = a

    if author_a is None:
        author_a = pseud_a
        pseud_a = None

    author = {"author": author_a.text, "author_link": href(author_a)}
    if pseud_a is not None:
        author["pseud"] = pseud_a.text
        author["pseud_link"] = href(pseud_a)
    else:
        author["pseud"] = ""
        author["pseud_link"] = ""
    author["id"] = f"{author['author']}/{author['pseud']}"
    return author

def simple_match(regex, string):
    return str(re.search(regex, string).group(1))

def extract_author_metadata(author, author_blurb):
    links = author_blurb.select('h5 a')
    author["num_bookmarks"]=""
    author["num_works"]=""
    fandom_metadata = {}
    for a in links:
        url = href(a)
        if "fandom_id=" in url:
            fandom_id = int(simple_match('fandom_id=([0-9]+)',url))
            fandom_name = simple_match('[0-9]+ works? in (.*)',a.text)
            fandom_num = int(simple_match('([0-9])+ work.*', a.text))
            fandom_metadata[fandom_id]=[fandom_name, fandom_num, url]
        else:
            if url.endswith("works"):
                author["num_works"] = int(simple_match('([0-9]+) work.*',a.text))
            elif url.endswith("bookmarks"):
                author["num_bookmarks"] = int(simple_match('([0-9]+) bookmark.*',a.text))
            else:
                print("Found strange author blurb url:")
                print(author_blurb)
                print(url)
    
    fandoms = list(fandom_metadata.keys())
    fandoms.sort()
    author["fandom_info"] = []
    for fandom in fandoms:
        author["fandom_info"] += fandom_metadata[fandom]


# 
# update the url to move to the next page
# note that if you go too far, ao3 won't error, 
# but there will be no works listed
# 
def update_url_to_next_page():
    global url
    key = "page="
    start = url.find(key)

    # there is already a page indicator in the url
    if (start != -1):
        # find where in the url the page indicator starts and ends
        page_start_index = start + len(key)
        page_end_index = url.find("&", page_start_index)
        # if it's in the middle of the url
        if (page_end_index != -1):
            page = int(url[page_start_index:page_end_index]) + 1
            url = url[:page_start_index] + str(page) + url[page_end_index:]
        # if it's at the end of the url
        else:
            page = int(url[page_start_index:]) + 1
            url = url[:page_start_index] + str(page)

    # there is no page indicator, so we are on page 1
    else:
        # there are other modifiers
        if (url.find("?") != -1):
            url = url + "&page=2"
        # there an no modifiers yet
        else:
            url = url + "?page=2"

# 
# after every page, write the gathered ids
# to the csv, so a crash doesn't lose everything.
# include the url where it was found,
# so an interrupted search can be restarted
# 
def write_ids_to_csv(ids):
    global num_recorded_authors
    with open(csv_name + ".csv", 'a', newline="") as csvfile:
        wr = csv.writer(csvfile, delimiter=',')
        if (not_finished()):
            wr.writerow([url,"",""])
        for id in ids:
            if (not_finished()):
                wr.writerow(["",id['author'], id['pseud'], id['author_link'], id['pseud_link'], id['num_works'],id['num_bookmarks']]+id['fandom_info'])
                num_recorded_authors = num_recorded_authors + 1
            else:
                break

# 
# if you want everything, you're not done
# otherwise compare recorded against requested.
# recorded doesn't update until it's actually written to the csv.
# If you've gone too far and there are no more fic, end. 
# 
def not_finished():
    if (page_empty):
        return False

    if (num_requested_authors == -1):
        return True
    else:
        if (num_recorded_authors < num_requested_authors):
            return True
        else:
            return False

# 
# include a text file with the starting url,
# and the number of requested fics
# 
def make_readme():
    with open(csv_name + "_readme.txt", "a") as text_file:
        text_file.write(f"\nretrieved on: {datetime.datetime.now()}\nnum_requested_authors: {num_requested_authors}\nurl: {url}\n")

# reset flags to run again
# note: do not reset seen_ids
def reset():
    global page_empty
    global num_recorded_authors
    page_empty = False
    num_recorded_authors = 0

def process_for_ids(header_info=''):
    while(not_finished()):
        # 5 second delay between requests as per AO3's terms of service
        time.sleep(5)
        ids = get_ids(header_info)
        write_ids_to_csv(ids)
        update_url_to_next_page()

def load_existing_ids():
    global seen_ids
    global url
    global continue_csv

    new_url = ""

    if (os.path.exists(csv_name + ".csv")):
        print("skipping existing IDs...\n")
        with open(csv_name + ".csv", 'r') as csvfile:
            id_reader = csv.reader(csvfile)
            for row in id_reader:
                if row[0].startswith("http"):
                    new_url = row[0]
                seen_ids.add(f"{row[1]}/{row[2]}")
        if continue_csv and new_url != "":
            print (f"Continuing with:\n{new_url}:\nRather than:\n{url}")
            url = new_url
    else:
        print("no existing file; creating new file...\n")
        with open(csv_name + ".csv", 'a', newline="") as csvfile:
            wr = csv.writer(csvfile, delimiter=',')
            wr.writerow(['current search page', 'author','pseud','author link', 'pseud link', 'num works', 'num bookmarks', 'fandom 1', 'num works in fandom', 'link to works in fandom', 'fandom 2 etc'])

def main():
    header_info = get_args()
    make_readme()

    print ("loading existing file ...\n")
    load_existing_ids()

    print("processing...\n")

    process_for_ids(header_info)

    print("That's all, folks.")

main()
