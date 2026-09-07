##############################################################################
#
# Copyright (c) 2006-2007 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Grok utility functions.
"""
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse

from grokcore.security.util import check_permission
from zope.component import getMultiAdapter
from zope.contentprovider.interfaces import IContentProvider
from zope.security.checker import NamesChecker
from zope.security.checker import defineChecker
from zope.traversing.browser.absoluteurl import _safe as SAFE_URL_CHARACTERS
from zope.traversing.browser.interfaces import IAbsoluteURL

from grokcore.view import directive


ASIS = object()


def url(request, obj, name=None, skin=ASIS, data=None):
    url = getMultiAdapter((obj, request), IAbsoluteURL)()
    if name is not None:
        url += '/' + quote(name.encode('utf-8'), SAFE_URL_CHARACTERS)

    if skin is not ASIS:
        # Remove whatever ``++skin++[name]`` is active.
        parts = list(urlparse(url))
        path = parts[2]
        if path.startswith('/++skin++'):
            # Find next / in the path.
            idx = path.find('/', 1)
            path = path[idx:]
        if skin is not None:
            # If a skin is set, add ``++skin++`` as the leading path segment.
            if isinstance(skin, str):
                path = f'/++skin++{skin}{path}'
            else:
                path = '/++skin++{}{}'.format(
                    directive.skin.bind().get(skin), path)

        parts[2] = path
        url = urlunparse(parts)

    if not data:
        return url

    if not isinstance(data, dict):
        raise TypeError('url() data argument must be a dict.')

    for k, v in data.items():
        if isinstance(v, str):
            data[k] = v.encode('utf-8')
        if isinstance(v, (list, set, tuple)):
            data[k] = [
                isinstance(item, str) and item.encode('utf-8')
                or item for item in v]

    return url + '?' + urlencode(data, doseq=True)


def render_provider(context, request, view, name):
    provider = getMultiAdapter(
        (context, request, view), interface=IContentProvider, name=name)
    provider.update()
    return provider.render()


def make_checker(factory, view_factory, permission, method_names=None):
    if method_names is None:
        method_names = ['__call__']
    if permission is not None:
        check_permission(factory, permission)
    if permission is None or permission == 'zope.Public':
        checker = NamesChecker(method_names)
    else:
        checker = NamesChecker(method_names, permission)
    defineChecker(view_factory, checker)
