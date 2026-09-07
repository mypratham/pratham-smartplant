##############################################################################
#
# Copyright (c) 2001, 2002 Zope Foundation and Contributors.
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
"""HTTP Publication
"""
import zope.component
from zope.publisher.interfaces.http import IHTTPException
from zope.publisher.interfaces.http import \
    IMethodNotAllowed  # noqa: F401 E501 (BBB and long line)
from zope.publisher.interfaces.http import MethodNotAllowed
from zope.publisher.publish import mapply

from zope.app.publication.zopepublication import ZopePublication


class BaseHTTPPublication(ZopePublication):
    """Base for HTTP-based protocol publications"""

    def annotateTransaction(self, txn, request, ob):
        txn = super().annotateTransaction(
            txn, request, ob)
        request_info = request.method + ' ' + request.getURL()
        txn.setExtendedInfo('request_info', request_info)
        return txn


class HTTPPublication(BaseHTTPPublication):
    """Non-browser HTTP publication"""

    def callObject(self, request, ob):
        # Exception handling, dont try to call request.method
        orig = ob
        if not IHTTPException.providedBy(ob):
            ob = zope.component.queryMultiAdapter((ob, request),
                                                  name=request.method)
            ob = getattr(ob, request.method, None)
            if ob is None:
                raise MethodNotAllowed(orig, request)
        return mapply(ob, request.getPositionalArguments(), request)
