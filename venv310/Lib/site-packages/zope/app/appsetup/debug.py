##############################################################################
#
# Copyright (c) 2008 Zope Foundation and Contributors.
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
"""Debug a Zope Application

$Id$
"""


__docformat__ = 'restructuredtext'

import os
import sys

import zdaemon.zdoptions
import zope.event
import zope.processlifetime
from zope.app.publication.zopepublication import ZopePublication

import zope.app.appsetup.appsetup
import zope.app.appsetup.product


def load_options(args=None):
    if args is None:
        args = sys.argv[1:]
    options = zdaemon.zdoptions.ZDOptions()
    options.schemadir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'schema')
    options.realize(args)
    if options.configroot is None:
        options.usage("please specify a configuration file")
    options = options.configroot
    if options.path:
        sys.path[:0] = [os.path.abspath(p) for p in options.path]
    return options


def loadApplication(args=None):
    options = load_options(args)

    zope.app.appsetup.product.setProductConfigurations(
        options.product_config)

    zope.app.appsetup.config(options.site_definition)

    db = zope.app.appsetup.appsetup.multi_database(options.databases)[0][0]
    zope.event.notify(zope.processlifetime.DatabaseOpened(db))
    return db


def main(args=None):
    db = loadApplication(args)
    if "PYTHONSTARTUP" in os.environ:
        startup = os.environ["PYTHONSTARTUP"]
        with open(startup) as s:
            exec(compile(s.read(), startup, 'exec'))
    sys.modules['__main__'].root = db.open().root()[ZopePublication.root_name]
    print('The application root is known as `root`.')
    os.environ["PYTHONINSPECT"] = "true"


if __name__ == '__main__':
    main()
