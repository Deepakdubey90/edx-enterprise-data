# -*- coding: utf-8 -*-
"""
External Resource Link Report Generation Code.
"""
from __future__ import absolute_import, unicode_literals

from collections import Counter
from datetime import date
import operator
import logging
import os
import re
import sys
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse

from py2neo import Graph

from enterprise_reporting.utils import send_email_with_attachment

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def generate_aggregate_report_csv_string(processed_results):
    """
    Takes a dict of processed results and turns it into a string suitable
    to be written as a csv file

    Returns (unicode) string
    """
    csv_string = u'Course Key,Course Title,Partner,External Domain,Count\n'
    for course_key, data in processed_results.items():
        urls_sorted_by_counts = sorted(
            data['external_links'].items(),
            key=operator.itemgetter(1),
            reverse=True
        )
        stringified_urls_and_counts = [
            u'{},{}'.format(url, count)
            for url, count in urls_sorted_by_counts
        ]
        links = u'\n,,,'.join(stringified_urls_and_counts)
        csv_string += u'{},"{}",{},{}\n'.format(
            course_key,
            data['course_title'],
            data['organization'],
            links,
        )
    return csv_string


def generate_exhaustive_report_csv_string(processed_results):
    """
    Takes a dict of processed results and turns it into a string suitable
    to be written as a csv file

    Returns (unicode) string
    """
    csv_string = u'Course Key,Course Title,Partner,External Links\n'
    for course_key, data in processed_results.items():
        links = u'\n,,,'.join(data['external_links'])
        csv_string += u'{},"{}",{},{}\n'.format(
            course_key,
            data['course_title'],
            data['organization'],
            links,
        )
    return csv_string


def gather_links_from_html(html_string):
    """
    Takes some html blob as a string and extracts any external links, and
    returns them as a set
    """
    pattern = 'https?://.*?[" <]'
    links = set([
        link[0:-1]
        for link in re.findall(pattern, html_string,)
        if (not link.lower().endswith('.png"') and
            not link.lower().endswith('.jpg"') and
            not link.lower().endswith('.jpeg"') and
            not link.lower().endswith('.gif"') and
            not '.edx.org' in link)
    ])
    return links


def process_coursegraph_results(raw_results, domains_and_counts=False):
    """
    Takes the data from a coursegraph query

    domains_and_counts - specfies that urls should be stripped down to only
                         their domain, and then a count of occurences is also
                         added to processed_results dixt

    Returns a dict with course keys as the key and dict data about that course
    as value
    """
    processed_results = {}
    for entry in raw_results:
        course_key = entry['h.course_key']
        # Only want new style course keys to exclude archived courses
        if not course_key.startswith('course-'):
            continue

        external_links = gather_links_from_html(entry['h.data'])

        if not external_links:
            continue

        if domains_and_counts:
            # change each link to just the domain
            external_links = [
                '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(link))
                for link in external_links
            ]
            # calculate the unique counts for all the urls
            links_with_counts = dict(Counter(external_links))

            if course_key not in processed_results:
                processed_results[course_key] = {
                    'course_title': entry['course_title'],
                    'organization': entry['organization'],
                    'external_links': links_with_counts,
                }
            else:
                for link, count in links_with_counts.items():
                    if link in processed_results[course_key]['external_links']:
                        processed_results[course_key]['external_links'][link] += count
                    else:
                        processed_results[course_key]['external_links'][link] = count
        else:
            if course_key not in processed_results:
                processed_results[course_key] = {
                    'course_title': entry['course_title'],
                    'organization': entry['organization'],
                    'external_links': external_links,
                }
            else:
                processed_results[course_key]['external_links'].update(external_links)

    return processed_results


def query_coursegraph():
    """
    Calls coursegraph with cypher query and returns query data

    The data is a list of dicts where each dict contains keys that correspond
    to what is being returned in the query
    """
    graph = Graph(
        bolt=True,
        http_port=os.environ.get('COURSEGRAPH_PORT'),
        host=os.environ.get('COURSEGRAPH_HOST'),
        secure=True,
    )
    query = '''MATCH
                (c:course)-[:PARENT_OF*]->(h:html) 
              WHERE 
                h.data =~ '.*https?://.*'
              RETURN
                c.display_name as course_title,
                c.org as organization,
                h.course_key, 
                h.data'''
    results = graph.run(query)
    return results.data()


def generate_and_email_report():
    """
    Generates a report an sends it as an email with an attachment
    """
    LOGGER.info("Querying Course Graph DB...")
    raw_results = query_coursegraph()

    LOGGER.info("Generating exhaustive external links spreadsheet...")
    exhaustive_report = generate_exhaustive_report_csv_string(
        process_coursegraph_results(raw_results)
    )

    LOGGER.info("Generating aggregate external links spreadsheet...")
    aggregate_report = generate_aggregate_report_csv_string(
        process_coursegraph_results(raw_results, domains_and_counts=True)
    )

    attachments = [
        exhaustive_report.encode('utf-8'),
        aggregate_report.encode('utf-8'),
    ]

    today = str(date.today())
    filenames = [
        'external-resource-link-report-{}.csv'.format(today),
        'external-resource-domain-report-{}.csv'.format(today),
    ]

    subject = 'External Resource Link Report'
    body = '''Dear Customer Success,
Find attached a file containing course keys and their respective
external resource links.

If you have any questions/concerns with the report, please ask the
Enterprise Team (kindly)!

Sincerely,
The Enterprise Team'''

    from_email = os.environ.get('SEND_EMAIL_FROM')

    LOGGER.info("Emailing spreadsheets...")
    send_email_with_attachment(
        subject,
        body,
        from_email,
        TO_EMAILS.split(','),
        filename=filenames,
        attachment_data=attachments
    )


if __name__ == '__main__':
    TO_EMAILS = sys.argv[1]
    generate_and_email_report()
