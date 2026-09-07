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
"""Publication factories.

This module provides factories for tuples (request, publication).
"""
from zope.interface import implementer
from zope.publisher.browser import BrowserRequest
from zope.publisher.http import HTTPRequest
from zope.publisher.xmlrpc import XMLRPCRequest

from zope import component
from zope.app.publication import interfaces
from zope.app.publication.browser import BrowserPublication
from zope.app.publication.http import HTTPPublication
from zope.app.publication.interfaces import IRequestPublicationFactory
from zope.app.publication.soap import SOAPPublication
from zope.app.publication.xmlrpc import XMLRPCPublication


@implementer(IRequestPublicationFactory)
class SOAPFactory:

    def canHandle(self, environment):
        self.soap_req = component.queryUtility(interfaces.ISOAPRequestFactory)
        return bool(environment.get('HTTP_SOAPACTION') and self.soap_req)

    def __call__(self):
        return self.soap_req, SOAPPublication


@implementer(IRequestPublicationFactory)
class XMLRPCFactory:

    def canHandle(self, environment):
        return True

    def __call__(self):
        request_class = component.queryUtility(
            interfaces.IXMLRPCRequestFactory, default=XMLRPCRequest)
        return request_class, XMLRPCPublication


@implementer(IRequestPublicationFactory)
class HTTPFactory:

    def canHandle(self, environment):
        return True

    def __call__(self):
        request_class = component.queryUtility(
            interfaces.IHTTPRequestFactory, default=HTTPRequest)
        return request_class, HTTPPublication


@implementer(IRequestPublicationFactory)
class BrowserFactory:

    def canHandle(self, environment):
        return True

    def __call__(self):
        request_class = component.queryUtility(
            interfaces.IBrowserRequestFactory, default=BrowserRequest)
        return request_class, BrowserPublication
