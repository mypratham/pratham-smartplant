#############################################################################
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
"""Grokkers for the various components."""

import grokcore.component
import martian
from martian.error import GrokError

from grokcore.formlib import components
from grokcore.formlib import formlib


class FormGrokker(martian.ClassGrokker):
    martian.component(components.GrokForm)
    martian.directive(grokcore.component.context)

    def execute(self, factory, config, context, **kw):
        # Set up form_fields from context class if they haven't been
        # configured manually already.
        if getattr(factory, 'form_fields', None) is None:
            factory.form_fields = formlib.get_auto_fields(context)

        if not getattr(factory.render, 'base_method', False):
            raise GrokError(
                "It is not allowed to specify a custom 'render' "
                "method for form %r. Forms either use the default "
                "template or a custom-supplied one." % factory,
                factory)
        return True
