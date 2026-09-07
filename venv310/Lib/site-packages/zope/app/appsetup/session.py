##############################################################################
#
# Copyright (c) 2002-2009 Zope Foundation and Contributors.
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
"""Bootstrap code for sessions."""

import transaction
from zope.session.http import CookieClientIdManager
from zope.session.interfaces import IClientIdManager
from zope.session.interfaces import ISessionDataContainer
from zope.session.session import PersistentSessionDataContainer

from zope.app.appsetup.bootstrap import ensureUtility
from zope.app.appsetup.bootstrap import getInformationFromEvent


def bootStrapSubscriber(event):
    """Subscriber to the IDataBaseOpenedEvent

    Create utility at that time if not yet present
    """
    db, connection, root, root_folder = getInformationFromEvent(event)

    ensureUtility(
        root_folder,
        IClientIdManager, 'CookieClientIdManager',
        CookieClientIdManager)
    ensureUtility(
        root_folder,
        ISessionDataContainer, 'PersistentSessionDataContainer',
        PersistentSessionDataContainer)

    transaction.commit()
    connection.close()
