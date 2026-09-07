##############################################################################
#
# Copyright (c) 2011 Zope Foundation and Contributors.
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

from zope.browser.interfaces import ISystemErrorView
from zope.event import notify
from zope.interface import implementer
from zope.publisher.interfaces.http import IHTTPException

from zope.errorview.interfaces import HandleExceptionEvent


@implementer(ISystemErrorView)
class SystemErrorViewMixin:
    """An optional mixin to indicate a particular error view to be an "system
    error" view. This indicates the publication object to log the error again
    with the error reporting utility.

    """

    def isSystemError(self):
        return True


@implementer(IHTTPException)
class ExceptionViewBase:

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def update(self):
        self.request.response.setStatus(500)
        self.request.response.setHeader(
            'Content-Type', 'text/plain;charset=utf-8')

    def render(self):
        return ''

    def __call__(self):
        notify(HandleExceptionEvent(self.request))
        self.update()
        return self.render()

    def __str__(self):
        return self()


class ExceptionView(ExceptionViewBase):
    pass


class TraversalExceptionView(ExceptionViewBase):

    def update(self):
        super().update()
        if self.request.method == 'MKCOL' and self.request.getTraversalStack():
            # MKCOL with non-existing parent.
            self.request.response.setStatus(409)
        else:
            self.request.response.setStatus(404)


class UnauthorizedView(ExceptionViewBase):

    def update(self):
        super().update()
        self.request.unauthorized('basic realm="Zope"')
        self.request.response.setStatus(401)


class MethodNotAllowedView(ExceptionViewBase):

    # XXX define an interface for MethodNotAllowedView components.

    def allowed(self):
        # XXX how to determine the allowed HTTP methods?  XXX we need
        # a safe way to determine the allow HTTP methods. Or should we
        # let the application handle it?
        return []

    def update(self):
        super().update()
        allow = self.allowed()
        self.request.response.setStatus(405)
        self.request.response.setHeader('Allow', ', '.join(allow))
