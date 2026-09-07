##############################################################################
#
# Copyright (c) 2003, 2004 Zope Foundation and Contributors.
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
"""Bootstrap tests"""
import doctest
import os
import sys
import unittest
from urllib.request import pathname2url

import transaction
import ZConfig
import zope.component
from ZODB.MappingStorage import DB
from zope.app.publication.zopepublication import ZopePublication
from zope.component.testlayer import ZCMLFileLayer
from zope.error.error import ErrorReportingUtility
from zope.error.interfaces import IErrorReportingUtility
from zope.processlifetime import DatabaseOpened
from zope.session.interfaces import IClientIdManager
from zope.session.interfaces import ISessionDataContainer
from zope.site.folder import Folder
from zope.site.folder import rootFolder
from zope.site.interfaces import IRootFolder
from zope.site.site import LocalSiteManager
from zope.traversing.api import getPath
from zope.traversing.api import traverse

import zope.app.appsetup
from zope.app.appsetup.bootstrap import bootStrapSubscriber
from zope.app.appsetup.bootstrap import ensureUtility
from zope.app.appsetup.bootstrap import getInformationFromEvent
from zope.app.appsetup.errorlog import \
    bootStrapSubscriber as errorlogBootStrapSubscriber
from zope.app.appsetup.session import \
    bootStrapSubscriber as sessionBootstrapSubscriber


layer = ZCMLFileLayer(zope.app.appsetup)


class EventStub:

    def __init__(self, db):
        self.database = db

#
# TODO: some methods from the bootstrap module are not tested
#


class TestBootstrapSubscriber(unittest.TestCase):

    layer = layer

    def setUp(self):
        self.db = DB()

    def tearDown(self):
        transaction.abort()
        self.db.close()

    def createRootFolder(self):
        cx = self.db.open()
        root = cx.root()
        self.root_folder = rootFolder()
        root[ZopePublication.root_name] = self.root_folder
        transaction.commit()
        cx.close()

    def createRFAndSM(self):
        cx = self.db.open()
        root = cx.root()
        self.root_folder = rootFolder()
        root[ZopePublication.root_name] = self.root_folder
        self.site_manager = LocalSiteManager(self.root_folder)
        self.root_folder.setSiteManager(self.site_manager)

        sub_folder = Folder()
        self.root_folder["sub_folder"] = sub_folder
        sub_site_manager = LocalSiteManager(sub_folder)
        sub_folder.setSiteManager(sub_site_manager)

        transaction.commit()
        cx.close()

    def test_notify(self):
        for setup in (lambda: None), self.createRootFolder, self.createRFAndSM:
            setup()
        bootStrapSubscriber(EventStub(self.db))
        cx = self.db.open()
        root = cx.root()
        root_folder = root.get(ZopePublication.root_name, None)
        self.assertTrue(IRootFolder.providedBy(root_folder))
        package_name = '/++etc++site/default'
        traverse(root_folder, package_name)
        cx.close()

    def test_ensureUtilityForSubSite(self):
        self.createRFAndSM()

        db, connection, root, root_folder = getInformationFromEvent(
            EventStub(self.db))

        sub_folder = root_folder['sub_folder']
        ensureUtility(sub_folder, IErrorReportingUtility,
                      'ErrorReporting', ErrorReportingUtility,
                      'ErrorReporting')

        # Make sure it was created on the sub folder, not the root folder
        got_utility = zope.component.getUtility(IErrorReportingUtility,
                                                name='ErrorReporting',
                                                context=sub_folder)
        got_path = getPath(got_utility)
        self.assertEqual(
            "/sub_folder/++etc++site/default/ErrorReporting", got_path)

    def test_ensureUtility(self):
        self.createRFAndSM()

        db, connection, root, root_folder = getInformationFromEvent(
            EventStub(self.db))

        # TODO: check EventSub
        root_folder = self.root_folder
        for i in range(2):
            cx = self.db.open()
            utility = ensureUtility(root_folder, IErrorReportingUtility,
                                    'ErrorReporting', ErrorReportingUtility,
                                    'ErrorReporting')
            utility2 = ensureUtility(root_folder, IErrorReportingUtility,
                                     'ErrorReporting2', ErrorReportingUtility,
                                     'ErrorReporting2')
            if utility is not None:
                name = utility.__name__
                name2 = utility2.__name__
            else:
                name = None
                name2 = None
            if i == 0:
                self.assertEqual(name, 'ErrorReporting')
                self.assertEqual(name2, 'ErrorReporting2')
            else:
                self.assertEqual(name, None)
                self.assertEqual(name2, None)

            root = cx.root()
            root_folder = root[ZopePublication.root_name]

            package_name = '/++etc++site/default'
            package = traverse(self.root_folder, package_name)

            self.assertTrue(IErrorReportingUtility.providedBy(
                traverse(package, 'ErrorReporting')))
            self.assertTrue(IErrorReportingUtility.providedBy(
                traverse(package, 'ErrorReporting2')))
            transaction.commit()

        cx.close()

    def test_errorReportingSetup(self):
        """Error reporting is set up by an event handler in this package.

        We test whether the event handler works.
        """
        self.createRFAndSM()

        event = DatabaseOpened(self.db)
        # this will open and close the database by itself
        errorlogBootStrapSubscriber(event)

        # this will re-open the database
        db, connection, root, root_folder = getInformationFromEvent(event)

        got_utility = zope.component.getUtility(IErrorReportingUtility,
                                                context=root_folder)
        self.assertTrue(IErrorReportingUtility.providedBy(got_utility))
        # we need to close again in the end
        connection.close()

    def test_bootstrapSusbcriber(self):
        self.createRFAndSM()

        event = DatabaseOpened(self.db)
        # this will open and close the database by itself
        sessionBootstrapSubscriber(event)

        db, connection, root, root_folder = getInformationFromEvent(event)

        got_utility = zope.component.getUtility(IClientIdManager,
                                                context=root_folder)
        self.assertTrue(IClientIdManager.providedBy(got_utility))

        got_utility = zope.component.getUtility(ISessionDataContainer,
                                                context=root_folder)
        self.assertTrue(ISessionDataContainer.providedBy(got_utility))

        # we need to close again in the end
        connection.close()


class TestConfigurationSchema(unittest.TestCase):

    def setUp(self):
        self.here = os.path.dirname(os.path.abspath(__file__))
        self.schema_dir = os.path.join(self.here, "schema")

    def path2url(self, path):
        urlpath = pathname2url(path)
        while urlpath.startswith("/"):
            urlpath = urlpath[1:]
        return "file:///" + urlpath

    def test_productconfig_xml(self):
        path = os.path.join(self.schema_dir, "productconfig.xml")
        url = self.path2url(path)
        ZConfig.loadSchema(url)

    def test_schema_xml(self):
        path = os.path.join(self.schema_dir, "schema.xml")
        url = self.path2url(path)
        ZConfig.loadSchema(url)


class DebugLayer(ZCMLFileLayer):

    def setUp(self):
        super().setUp()
        self.stderr = sys.stderr
        self.argv = list(sys.argv)
        self.olddir = os.getcwd()
        os.chdir(os.path.join(os.path.dirname(__file__), 'testdata'))
        from zope.security.management import endInteraction
        endInteraction()

    def tearDown(self):
        sys.stderr = self.stderr
        sys.argv[:] = self.argv
        if hasattr(sys, 'ps1'):
            del sys.ps1
        os.chdir(self.olddir)
        # make sure we don't leave environment variables that would cause
        # Python to open an interactive console
        if 'PYTHONINSPECT' in os.environ:
            del os.environ['PYTHONINSPECT']
        from zope.security.management import endInteraction
        endInteraction()
        super().tearDown()


def test_suite():
    loadTestsFromTestCase = unittest.defaultTestLoader.loadTestsFromTestCase
    suite = unittest.TestSuite()
    suite.addTest(loadTestsFromTestCase(TestBootstrapSubscriber))
    suite.addTest(loadTestsFromTestCase(TestConfigurationSchema))

    dtflags = (
        doctest.ELLIPSIS
        | doctest.NORMALIZE_WHITESPACE
        | doctest.REPORT_NDIFF)

    test = doctest.DocTestSuite('zope.app.appsetup.appsetup')
    test.layer = layer
    suite.addTest(test)
    for filename in ['bootstrap.rst', 'product.rst']:
        test = doctest.DocFileSuite(filename, optionflags=dtflags)
        test.layer = layer
        suite.addTest(test)

    test = doctest.DocFileSuite('debug.rst')
    test.layer = DebugLayer(zope.app.appsetup)
    suite.addTest(test)
    suite.addTest(doctest.DocFileSuite(
        'testlayer.rst',
        optionflags=dtflags))

    return suite
