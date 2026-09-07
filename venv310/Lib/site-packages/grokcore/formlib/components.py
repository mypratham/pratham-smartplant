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
"""Formlib-based components"""

import datetime
import os
import warnings

import pytz

from grokcore.view import PageTemplateFile
from grokcore.view import View
from zope.formlib import form
from zope.interface import implementer_only
from zope.interface.common import idatetime
from zope.publisher.publish import mapply

from grokcore.formlib import formlib
from grokcore.formlib.interfaces import IGrokForm


default_form_template = PageTemplateFile(os.path.join(
    'templates', 'default_edit_form.pt'))
default_form_template.__grok_name__ = 'default_edit_form'
default_display_template = PageTemplateFile(os.path.join(
    'templates', 'default_display_form.pt'))
default_display_template.__grok_name__ = 'default_display_form'


class GrokForm:
    """Mix-in to consolidate zope.formlib's forms with grok.View and to
    add some more useful methods.

    The consolidation needs to happen because zope.formlib's Forms have
    update/render methods which have different meanings than
    grok.View's update/render methods.  We deal with this issue by
    'renaming' zope.formlib's update() to update_form() and by
    disallowing subclasses to have custom render() methods."""

    actions = form.Actions()

    def update(self):
        """Subclasses can override this method just like on regular
        grok.Views. It will be called before any form processing
        happens."""

    def update_form(self):
        """Update the form, i.e. process form input using widgets.

        On zope.formlib forms, this is what the update() method is.
        In grok views, the update() method has a different meaning.
        That's why this method is called update_form() in grok forms."""
        super().update()

    def render(self):
        """Render the form, either using the form template or whatever
        the actions returned in form_result."""
        # if the form has been updated, it will already have a result
        if self.form_result is None:
            if self.form_reset:
                # we reset, in case data has changed in a way that
                # causes the widgets to have different data
                self.resetForm()
                self.form_reset = False
            self.form_result = self._render_template()

        return self.form_result

    # Mark the render() method as a method from the base class. That
    # way we can detect whether somebody overrides render() in a
    # subclass (which we don't allow).
    render.base_method = True

    def __call__(self):
        mapply(self.update, (), self.request)
        if self.request.response.getStatus() in (302, 303):
            # A redirect was triggered somewhere in update().  Don't
            # continue rendering the template or doing anything else.
            return

        self.update_form()
        return self.render()


@implementer_only(IGrokForm)
class Form(GrokForm, form.FormBase, View):
    # We're only reusing the form implementation from zope.formlib, we
    # explicitly don't want to inherit the interface semantics (mostly
    # for the different meanings of update/render).

    template = default_form_template

    def applyData(self, obj, **data):
        return formlib.apply_data_event(obj, self.form_fields, data,
                                        self.adapters)

    # BBB -- to be removed in June 2007
    def applyChanges(self, obj, **data):
        warnings.warn("The 'applyChanges' method on forms is deprecated "
                      "and will disappear by June 2007. Please use "
                      "'applyData' instead.", DeprecationWarning, 2)
        return bool(self.applyData(obj, **data))


class AddForm(Form):
    pass


@implementer_only(IGrokForm)
class EditForm(GrokForm, form.EditFormBase, View):
    # We're only reusing the form implementation from zope.formlib, we
    # explicitly don't want to inherit the interface semantics (mostly
    # for the different meanings of update/render).

    template = default_form_template

    def applyData(self, obj, **data):
        return formlib.apply_data_event(obj, self.form_fields, data,
                                        self.adapters, update=True)

    # BBB -- to be removed in June 2007
    def applyChanges(self, obj, **data):
        warnings.warn("The 'applyChanges' method on forms is deprecated "
                      "and will disappear by June 2007. Please use "
                      "'applyData' instead.", DeprecationWarning, 2)
        return bool(self.applyData(obj, **data))

    @formlib.action("Apply")
    def handle_edit_action(self, **data):
        if self.applyData(self.context, **data):
            formatter = self.request.locale.dates.getFormatter(
                'dateTime', 'medium')

            try:
                time_zone = idatetime.ITZInfo(self.request)
            except TypeError:
                time_zone = pytz.UTC

            self.status = "Updated on %s" % formatter.format(
                datetime.datetime.now(time_zone)
            )
        else:
            self.status = 'No changes'


@implementer_only(IGrokForm)
class DisplayForm(GrokForm, form.DisplayFormBase, View):
    # We're only reusing the form implementation from zope.formlib, we
    # explicitly don't want to inherit the interface semantics (mostly
    # for the different meanings of update/render).

    template = default_display_template
