##############################################################################
#
# Copyright (c) 2003 Zope Foundation and Contributors.
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
"""Tests for the HTTP Publication Request Factory.
"""
from unittest import TestCase

from zope.component.testing import PlacelessSetup
from zope.configuration.exceptions import ConfigurationError
from zope.interface.verify import verifyClass

from zope import component
from zope import interface
from zope.app.publication import interfaces
from zope.app.publication.interfaces import IRequestPublicationRegistry
from zope.app.publication.requestpublicationfactories import BrowserFactory
from zope.app.publication.requestpublicationfactories import HTTPFactory
from zope.app.publication.requestpublicationfactories import SOAPFactory
from zope.app.publication.requestpublicationfactories import XMLRPCFactory
from zope.app.publication.requestpublicationregistry import \
    RequestPublicationRegistry


def DummyFactory():
    return object


class DummyRequestFactory:
    def __call__(self, input_stream, env):
        self.input_stream = input_stream
        self.env = env
        return self

    def setPublication(self, pub):
        self.pub = pub


class PickyFactory:
    def __init__(self, name):
        self.name = name

    def __call__(self, name, input_stream, env, can_handle=True):
        self.input_stream = input_stream
        self.env = env
        return self

    def canHandle(self, env):
        return 'CAN_HANDLE' in env

    def setPublication(self, pub):
        self.pub = pub


class NotSoPickyFactory(PickyFactory):
    def canHandle(self, env):
        return True


class Test(PlacelessSetup, TestCase):

    def test_interface(self):
        verifyClass(IRequestPublicationRegistry, RequestPublicationRegistry)

    def test_registration(self):
        r = RequestPublicationRegistry()
        xmlrpc_f = DummyFactory()
        r.register('POST', 'text/xml', 'xmlrpc', 0, xmlrpc_f)
        soap_f = DummyFactory()
        r.register('POST', 'text/xml', 'soap', 1, soap_f)
        browser_f = DummyFactory()
        r.register('*', '*', 'browser_default', 0, browser_f)
        factories = r.getFactoriesFor('POST', 'text/xml')
        self.assertEqual(
            factories,
            [{'name': 'soap', 'priority': 1, 'factory': object},
             {'name': 'xmlrpc', 'priority': 0, 'factory': object}])
        self.assertEqual(r.getFactoriesFor('POST', 'text/html'), None)

    def test_configuration_same_priority(self):
        r = RequestPublicationRegistry()
        r.register('POST', 'text/xml', 'xmlrpc', 0, DummyFactory)
        r.register('POST', 'text/xml', 'soap', 1, DummyFactory())
        # try to register a factory with the same priority
        self.assertRaises(ConfigurationError, r.register,
                          'POST', 'text/xml', 'soap2', 1, DummyFactory())

    def test_configuration_reregistration(self):
        r = RequestPublicationRegistry()
        r.register('POST', 'text/xml', 'xmlrpc', 0, DummyFactory)
        r.register('POST', 'text/xml', 'soap', 1, DummyFactory())
        # re-register 'soap' but with priority 2
        r.register('POST', 'text/xml', 'soap', 2, DummyFactory())
        factory_data = r.getFactoriesFor('POST', 'text/xml')
        priorities = [item['priority'] for item in factory_data]
        self.assertEqual(priorities, [2, 0])

    def test_realfactories(self):
        r = RequestPublicationRegistry()
        r.register('POST', '*', 'post_fallback', 0, HTTPFactory())
        r.register('POST', 'text/xml', 'xmlrpc', 1, XMLRPCFactory())
        r.register('POST', 'text/xml', 'soap', 2, SOAPFactory())
        r.register('GET', '*', 'http', 0, HTTPFactory())
        r.register('PUT', '*', 'http', 0, HTTPFactory())
        r.register('HEAD', '*', 'http', 0, HTTPFactory())
        r.register('*', '*', 'http', 1, BrowserFactory())

        self.assertEqual(len(r.getFactoriesFor('POST', 'text/xml')), 2)
        self.assertEqual(
            len(r.getFactoriesFor('POST', 'text/xml; charset=utf-8')), 2)
        self.assertEqual(len(r.getFactoriesFor('POST', '*')), 1)
        self.assertEqual(r.getFactoriesFor('GET', 'text/html'), None)
        self.assertEqual(len(r.getFactoriesFor('HEAD', '*')), 1)

        env = {
            'SERVER_URL': 'http://127.0.0.1',
            'HTTP_HOST': '127.0.0.1',
            'CONTENT_LENGTH': '0',
            'GATEWAY_INTERFACE': 'TestFooInterface/1.0',
        }

        soaprequestfactory = DummyRequestFactory()
        interface.directlyProvides(
            soaprequestfactory, interfaces.ISOAPRequestFactory)
        component.provideUtility(soaprequestfactory)

        self.assertIsInstance(
            r.lookup('POST', 'text/xml', env),
            XMLRPCFactory
        )
        env['HTTP_SOAPACTION'] = 'foo'
        self.assertIsInstance(
            r.lookup('POST', 'text/xml', env),
            SOAPFactory
        )
        self.assertIsInstance(
            r.lookup('FOO', 'zope/sucks', env),
            BrowserFactory
        )

    def test_fallback_to_generic_publicationfactory(self):
        # If a found publication factory for the given method/mime-type
        # claims it cannot handle the request after all, we fall back
        # to a more generically registered factory.
        r = RequestPublicationRegistry()
        r.register('*', '*', 'generic', 0, NotSoPickyFactory('a'))
        r.register('GET', '*', 'genericget', 0, NotSoPickyFactory('b'))
        r.register('GET', 'foo/bar', 'pickyget', 2, PickyFactory('P'))
        env = {
            'SERVER_URL': 'http://127.0.0.1',
            'HTTP_HOST': '127.0.0.1',
            'CAN_HANDLE': 'true',
        }
        self.assertEqual('a', r.lookup('FOO', 'zope/epoz', env).name)
        self.assertEqual('b', r.lookup('GET', 'zope/epoz', env).name)
        # The picky factory find the "CAN_HANDLE" key in the env, so yes
        # it can handle request, and the lookup succeeds.
        self.assertEqual('P', r.lookup('GET', 'foo/bar', env).name)
        # Now we alter the environment, so the picky factory says it
        # cannot handle the request and we fallback to a more generically
        # registered factory.
        del env['CAN_HANDLE']
        self.assertEqual('b', r.lookup('GET', 'foo/bar', env).name)

    def test_fail_if_no_factory_can_be_found(self):
        from zope.configuration.exceptions import ConfigurationError

        # If cannot find a factory that would handle the requestm at all
        # we fail with a clear message. The lookup //used// to return None
        # in these case without the callee handling that case.
        r = RequestPublicationRegistry()
        env = {
            'SERVER_URL': 'http://127.0.0.1',
            'HTTP_HOST': '127.0.0.1',
            'CAN_HANDLE': 'true',
        }
        # No registration found for the method/mime-type.
        r.register('GET', 'foo/bar', 'foobarget', 0, NotSoPickyFactory('a'))
        self.assertRaises(
            ConfigurationError,
            r.lookup, 'GET', 'zope/epoz', env)
        self.assertRaises(
            ConfigurationError,
            r.lookup, 'BAZ', 'foo/bar', env)
        # If the only found factory cannot handle the request after all, we
        # obviously fail too.
        r.register('GET', 'frop/fropple', 'pickyget', 2, PickyFactory('P'))
        self.assertEqual('P', r.lookup('GET', 'frop/fropple', env).name)
        del env['CAN_HANDLE']
        self.assertRaises(
            ConfigurationError,
            r.lookup, 'BAZ', 'frop/fropple', env)
