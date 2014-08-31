import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.parse

from multiprocessing import Pool
from contextlib import closing
from datetime import datetime, timezone

import lxml.html

from lxml.html import builder as E

import slob

from . import dictionary

HTML = 'text/html; charset=utf-8'
CSS = 'text/css'
RE_SPACE = re.compile(r'\s+')
LINK_TAG = '<link rel="stylesheet" href="{0}" type="text/css"></link>'


def read_file(name):
    with (open(os.path.join(os.path.dirname(__file__), name), 'rb')) as f:
        return f.read()


def p(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def split_frag(s):
    if '#' in s:
        return s.split('#', maxsplit=1)
    return s, ''


def convert(item):
    try:
        return _convert(item)
    except Exception:
        traceback.print_exc()
        return (False, None, None)


def _convert(item):
    title, article, css_tags, article_url_template = item
    articletuple = json.loads(article.decode('utf-8'))
    if len(articletuple) == 3:
        text, _, meta = articletuple
    else:
        text, _ = articletuple
        meta = {}
    redirect = meta.get('r', meta.get('redirect', ''))
    if redirect:
        return (True, title, split_frag(redirect))

    key, fragment = split_frag(title)
    fragment = RE_SPACE.sub('_', fragment)

    doc = lxml.html.fromstring(text)

    #make footnotes work in browser without js
    for a in doc.cssselect('a[onclick]'):
        onclick = a.attrib['onclick']
        if onclick.startswith("return s('"):
            a.attrib['href'] = '#'+onclick[10:len(onclick)-2]
            del a.attrib['onclick']
    #make fragment references work in browser
    for h in doc.cssselect('h1,h2,h3,h4,h5,h6'):
        for item in h:
            if item.text:
                item.attrib['id'] = RE_SPACE.sub('_', item.text.strip())

    if article_url_template:
        article_url = article_url_template.replace(
            '$1', urllib.parse.quote(title))
        a = E.A(id="view-online-link", href=article_url)
        title_heading = doc.cssselect('h1')
        if len(title_heading) > 0:
            title_heading = title_heading[0]
            if title_heading.text:
                a.text = title_heading.text
                title_heading.text = ''
                title_heading.append(a)
        else:
            a.text = key
            title_heading = E.H1()
            title_heading.append(a)
            body = doc.find('body')
            if not body is None:
                body.insert(0, title_heading)
            else:
                doc.insert(0, title_heading)

    content = ''.join((
        '<html>'
        '<head>',
        css_tags,
        '</head>'
        '<body>',
        lxml.html.tostring(doc, encoding='unicode'),
        '</body>',
        '</html>'
    )) .encode('utf-8')
    return (False, content, (key, fragment))


def main():

    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('input_file', nargs='+', type=str,
                            help='Name of Aard Dictionary file to read')
    arg_parser.add_argument('-o', '--output-file', type=str,
                            help='Name of output slob file')
    arg_parser.add_argument('-c', '--compression',
                            choices=['lzma2', 'zlib'],
                            default='lzma2',
                            help='Name of compression to use')
    arg_parser.add_argument('-b', '--bin-size',
                            type=int,
                            default=384,
                            help='Minimum storage bin size in kilobytes')

    arg_parser.add_argument('-s', '--start',
                            type=int,
                            default=None,
                            help='Start index')

    arg_parser.add_argument('-e', '--end',
                            type=int,
                            default=None,
                            help='End index')

    arg_parser.add_argument('-u', '--uri', type=str,
                            default='',
                            help=('Value for uri tag. Slob-specific '
                                  'article URLs such as bookmarks can be '
                                  'migrated to another slob based on '
                                  'matching "uri" tag values'))
    arg_parser.add_argument('-l', '--license-name', type=str,
                            default='',
                            help=('Value for license.name tag. '
                                  'This should be name under which '
                                  'the license is commonly known.'))

    arg_parser.add_argument('-L', '--license-url', type=str,
                            default='',
                            help=('Value for license.url tag. '
                                  'This should be a URL for license text'))

    arg_parser.add_argument('-a', '--created-by', type=str,
                            default='',
                            help=('Value for created.by tag. '
                                  'Identifier (e.g. name or email) '
                                  'for slob file creator'))

    arg_parser.add_argument('-w', '--work-dir', type=str, default='.',
                            help=('Directory for temporary files '
                                  'created during compilation. '
                                  'Default: %(default)s'))

    args = arg_parser.parse_args()

    fnames = [os.path.expanduser(name) for name in args.input_file]
    outname = args.output_file
    if outname is None:
        basename = os.path.basename(fnames[0])
        noext, _ext = os.path.splitext(basename)
        outname = os.path.extsep.join((noext, 'slob'))

    t0 = time.time()
    sort_t0 = None
    aliases_t0 = None

    def observer(e):
        nonlocal t0, sort_t0, aliases_t0
        if e.name == 'begin_finalize':
            p('\nFinished adding content in %.2fs' % (time.time() - t0))
            t0 = time.time()
            p('\nFinalizing...')
        if e.name == 'end_finalize':
            p('\nFinilized in %.2fs' % (time.time() - t0))
        elif e.name == 'begin_resolve_aliases':
            p('\nResolving aliases...')
            aliases_t0 = time.time()
        elif e.name == 'end_resolve_aliases':
            p('\nResolved aliases in %.2fs' % (time.time() - aliases_t0))
        elif e.name == 'begin_sort':
            p('\nSorting...')
            sort_t0 = time.time()
        elif e.name == 'end_sort':
            p(' sorted in %.2fs' % (time.time() - sort_t0))

    with slob.create(outname,
                     compression=args.compression,
                     workdir=args.work_dir,
                     min_bin_size=args.bin_size*1024,
                     observer=observer) as w:
        css_tags = []
        for name in ('shared.css',
                     'mediawiki_shared.css',
                     'mediawiki_monobook.css'):
            key = '_'+name
            w.add(read_file(name), key, content_type=CSS)
            css_tags.append(LINK_TAG.format(key))
        css_tags = '\n'.join(css_tags)

        w.tag('license.name', args.license_name)
        w.tag('license.url', args.license_url)
        w.tag('created.by', args.created_by)

        for fname in fnames:
            with closing(dictionary.Volume(fname)) as d:

                article_url_template = d.article_url
                w.tag('label', d.title if d.title else fname)
                source = d.source if d.source else ''
                w.tag('source', d.source if d.source else '')
                w.tag('uri', args.uri if args.uri else source)
                w.tag('copyright', d.copyright if d.copyright else '')

                count = len(d.articles)
                start = args.start if args.start else 0
                end = args.end if args.end else count
                articles = ((d.words[i], d.articles[i],
                             css_tags, article_url_template)
                            for i in range(start, end))

                workers = Pool()
                result = workers.imap_unordered(convert, articles)

                for i, converted in enumerate(result):
                    if i % 100 == 0 and i != 0:
                        p('.')
                        if i and i % 5000 == 0:
                            p(' {0:.2f}%\n'.format(100*(i/count)))
                    redirect, content, key_frag = converted
                    if content is None:
                        p('x')
                        continue
                    if redirect:
                        w.add_alias(content, key_frag)
                    else:
                        w.add(content, key_frag, content_type=HTML)

    p('\nWrote {0}\n'.format(outname))
