##############################################################################
#
# Copyright (c) 2010 Zope Foundation and Contributors.
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

import transaction
import ZODB.ActivityMonitor
import ZODB.interfaces
import zope.processlifetime
from ZODB.DB import DB
from ZODB.DemoStorage import DemoStorage
from zope.app.publication.zopepublication import ZopePublication
from zope.component.testlayer import ZCMLFileLayer
from zope.event import notify

from zope import component


def createTestDB(name='main', base=None):
    """This create a test storage and register it.
    """
    storage = DemoStorage(name, base=base)
    db = DB(storage, database_name=name)
    db.setActivityMonitor(ZODB.ActivityMonitor.ActivityMonitor())

    # DB are registered as utilities
    component.provideUtility(db, ZODB.interfaces.IDatabase, name)

    # And we send a event that our DB is available
    notify(zope.processlifetime.DatabaseOpened(db))
    return db


class ZODBLayer(ZCMLFileLayer):
    """This layer load a ZCML configuration and create a test database.

    You can access the test database with layer.getRootFolder().
    """

    db = None
    db_name = 'main'
    connection = None

    def getRootFolder(self):
        """This return the root object of the database or assert if
        the database have not been created yet.
        """
        if self.connection is None:
            assert self.db is not None
            self.connection = self.db.open()
        return self.connection.root()[ZopePublication.root_name]

    def _close_db(self):
        # Close any opened connections
        if self.connection is not None:
            transaction.abort()
            self.connection.close()
            self.connection = None

        # Close the Database
        if self.db is not None:
            # Need to unregister DB
            base = component.getGlobalSiteManager()
            base.unregisterUtility(
                self.db, ZODB.interfaces.IDatabase, self.db_name)
            self.db.close()
            self.db = None

    def setUp(self):
        super().setUp()
        self.db = createTestDB(self.db_name)
        self.base_storage = self.db._storage
        self._base_db_open = True

    def testSetUp(self):
        if self._base_db_open:
            # This is the first time testSetUp is called.
            # We need to close down the database configuration
            # that we needed for performing global setup now.
            self._close_db()
            self._base_db_open = False
        super().testSetUp()
        self.db = createTestDB(self.db_name, self.base_storage)

    def testTearDown(self):
        self._close_db()
        super().testTearDown()
