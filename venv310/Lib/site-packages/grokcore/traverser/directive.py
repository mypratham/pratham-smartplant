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

import martian


class traversable(martian.Directive):
    """The `grok.traversable()` directive.

    Each time this directive is used inside of a class, it designates an
    attribute of that class which URLs should be able to traverse.  For
    example, the declaration:

        class Mammoth(grok.Model):
            grok.traversable('thighbone')

    means that if the URL `/app/mymammoth` designates a Mammoth, then
    `/app/mymammoth/thighbone` will also be a valid URL (assuming that
    the Mammoth instance, at runtime, indeed has an attribute by that
    name)!  By default, the name that must be appended to the URL should
    simply be the same as the name of the attribute; but by providing a
    `name` keyword argument, the programmer can designate another name
    to appear in the URL instead of the raw attribute name.

    """
    scope = martian.CLASS
    store = martian.DICT

    def factory(self, attr, name=None):
        if name is None:
            name = attr
        return (name, attr)
