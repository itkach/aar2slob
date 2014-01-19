import argparse
import json
import os
import re
import sys
import time
import urllib.parse

from multiprocessing import Pool
from contextlib import closing

from bs4 import BeautifulSoup

import slob

from . import dictionary

HTML = 'text/html; charset=utf-8'
CSS = 'text/css'
RE_HEADING = re.compile('h[1-6]')
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


RE_SPACE = re.compile(r'\s+')


def convert(item):
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
    soup = BeautifulSoup(text)
    #make footnotes work in browser without js
    for a in soup('a', onclick=True):
        onclick = a.get('onclick')
        if onclick.startswith("return s('"):
            a['href'] = '#'+onclick[10:len(onclick)-2]
            del a['onclick']
    #make fragment references work in browser
    for h in soup(RE_HEADING):
        h['id'] = RE_SPACE.sub('_', h.text)

    if article_url_template:
        article_url = article_url_template.replace(
            '$1', urllib.parse.quote(title))
        a = soup.new_tag('a')
        a['id'] = 'view-online-link'
        a['href'] = article_url
        title_heading = soup.find('h1')
        if title_heading:
            title_heading.string.wrap(a)

    content = ''.join((
        '<html>'
        '<head>',
        css_tags,
        '</head>'
        '<body>',
        str(soup),
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
    arg_parser.add_argument('-w', '--work-dir', type=str, default='.',
                            help=('Directory for temporary files '
                                  'created during compilation. '
                                  'Default: %(default)s'))

    args = arg_parser.parse_args()

    fnames = [os.path.expanduser(name) for name in args.input_file]
    outname = args.output_file
    if outname is None:
        basename = os.path.basename(fnames[0])
        noext,_ext = os.path.splitext(basename)
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

    with slob.create(outname, workdir=args.work_dir, observer=observer) as w:
        css_tags = []
        for name in ('shared.css',
                     'mediawiki_shared.css',
                     'mediawiki_monobook.css'):
            key = '_'+name
            w.add(read_file(name), key, content_type=CSS)
            css_tags.append(LINK_TAG.format(key))
        css_tags = '\n'.join(css_tags)

        for fname in fnames:
            with closing(dictionary.Volume(fname)) as d:

                article_url_template = d.article_url
                if d.title:
                    w.tag('label', d.title)
                if d.source:
                    w.tag('source', d.source)
                if d.copyright:
                    w.tag('copyright', d.copyright)

                count = len(d.articles)

                articles = ((d.words[i], d.articles[i],
                             css_tags, article_url_template) for i in range(count))

                workers = Pool()
                result = workers.imap_unordered(convert, articles)

                for i, converted in enumerate(result):
                    if i % 100 == 0 and i != 0:
                        p('.')
                        if i and i % 5000 == 0:
                            p(' {0:.2f}%\n'.format(100*(i/count)))
                    redirect, content, key_frag = converted
                    if redirect:
                        w.add_alias(content, key_frag)
                    else:
                        w.add(content, key_frag, content_type=HTML)

    p('\nWrote {0}\n'.format(outname))


if __name__ == '__main__':
    main()
