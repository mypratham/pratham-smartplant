"""\
Sample section data type for product configuration tests.

"""

import ZConfig.components.basic.mapping

import zope.app.appsetup.product


def sampleProductConfig(section):
    mapping = ZConfig.components.basic.mapping.mapping(section)
    mapping["product-name"] = section.getSectionName()

    # Since this is a product config, we need a product configuration object,
    # not a bare mapping:
    return zope.app.appsetup.product.FauxConfiguration(
        mapping["product-name"], mapping)
