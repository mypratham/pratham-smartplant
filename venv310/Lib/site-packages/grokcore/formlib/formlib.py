##############################################################################
#
# Copyright (c) 2006-2008 Zope Foundation and Contributors.
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
"""Custom implementations of formlib helpers
"""

import zope.event
import zope.formlib.form
import zope.interface
import zope.lifecycleevent
from grokcore.content import ObjectEditedEvent
from zope.formlib.interfaces import IInputWidget
from zope.interface.interfaces import IInterface
from zope.schema.interfaces import IField


class action(zope.formlib.form.action):
    """We override the action decorator we pass in our custom Action.
    """

    def __call__(self, success):
        action = Action(self.label, success=success, **self.options)
        self.actions.append(action)
        return action


class Action(zope.formlib.form.Action):

    def validate(self, data):
        errors = super().validate(data)
        if errors is None:
            errors = self.form.validate(self, data)
        errors.extend(ensure_required_fields_have_input(
            self.form.widgets, data))
        return errors

    def success(self, data):
        if self.success_handler is not None:
            return self.success_handler(self.form, **data)


def ensure_required_fields_have_input(widgets, data):
    errors = []
    for widget in widgets:
        if not IInputWidget.providedBy(widget):
            continue
        if not widget.context.required or widget.hasInput():
            continue
        name = widget.context.__name__
        error = zope.formlib.interfaces.WidgetInputError(
            name,
            widget.label,
            zope.schema.interfaces.RequiredMissing(name))
        widget._error = error
        errors.append(error)
    return errors


def Fields(*args, **kw):
    fields = []
    for key, value in list(kw.items()):
        if IField.providedBy(value):
            value.__name__ = key
            fields.append(value)
            del kw[key]
    fields.sort(key=lambda field: field.order)
    return zope.formlib.form.Fields(*(args + tuple(fields)), **kw)


def get_auto_fields(context):
    """Get the form fields for context.
    """
    # for an interface context, we generate them from that interface
    if IInterface.providedBy(context):
        return zope.formlib.form.Fields(context)
    # if we have a non-interface context, we're autogenerating them
    # from any schemas defined by the context
    fields = zope.formlib.form.Fields(*most_specialized_interfaces(context))
    # we pull in this field by default, but we don't want it in our form
    fields = fields.omit('__name__')
    return fields


AutoFields = get_auto_fields


def most_specialized_interfaces(context):
    """Get interfaces for an object without any duplicates.

    Interfaces in a declaration for an object may already have been seen
    because it is also inherited by another interface. Don't return the
    interface twice, as that would result in duplicate names when creating
    the form.
    """
    declaration = zope.interface.implementedBy(context)
    seen = []
    for iface in declaration.flattened():
        if interface_seen(seen, iface):
            continue
        seen.append(iface)
    return seen


def interface_seen(seen, iface):
    """Return True if interface already is seen.
    """
    for seen_iface in seen:
        if seen_iface.extends(iface):
            return True
    return False


def apply_data(context, form_fields, data, adapters=None, update=False):
    """Save form data (``data`` dict) on a ``context`` object.

    This is a beefed up version of zope.formlib.form.applyChanges().
    It allows you to specify whether values should be compared with
    the attributes on already existing objects or not, using the
    ``update`` parameter.

    Unlike zope.formlib.form.applyChanges(), it will return a
    dictionary of interfaces and their fields that were changed.  This
    is necessary to appropriately send IObjectModifiedEvents.
    """
    if adapters is None:
        adapters = {}

    changes = {}

    for form_field in form_fields:
        field = form_field.field
        # Adapt context, if necessary
        interface = form_field.interface
        adapter = adapters.get(interface)
        if adapter is None:
            if interface is None:
                adapter = context
            else:
                adapter = interface(context)
            adapters[interface] = adapter

        name = form_field.__name__
        newvalue = data.get(name, form_field)  # using form_field as marker

        if update:
            if ((newvalue is not form_field) and
                    (field.get(adapter) != newvalue)):
                field.set(adapter, newvalue)
                changes.setdefault(interface, []).append(name)
        else:
            if newvalue is not form_field:
                field.set(adapter, newvalue)
                changes.setdefault(interface, []).append(name)

    return changes


def apply_data_event(context, form_fields, data, adapters=None, update=False):
    """Like apply_data, but also sends an IObjectModifiedEvent.
    """
    changes = apply_data(context, form_fields, data, adapters, update)

    if changes:
        descriptions = []
        for interface, names in changes.items():
            descriptions.append(
                zope.lifecycleevent.Attributes(interface, *names))
        zope.event.notify(ObjectEditedEvent(context, *descriptions))

    return changes
