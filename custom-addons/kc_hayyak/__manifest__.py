# -*- coding: utf-8 -*-
{
    'name': "Hayyak Integration Module",

    'summary': """ Hayyak Integration Module 
    This module integrates Hayyak services with Odoo LMS.""",

    'description': """
        This module integrates Hayyak services with Odoo LMS. It includes features such as:
        - Partner enhancements for Hayyak users
        - Sale order modifications to handle Hayyak-specific data
        - Configuration settings for Hayyak API integration
    """,

    'author': "Alkhalejiah Ceatring Company",
    'website': "http://www.alkhalejiah.com",
    'license': 'LGPL-3',
    'category': 'Hidden/Tools',

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/14.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '0.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'kc_api_base', 'lms_management'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'data/email_template.xml',
        'views/partner.xml',
        'views/inherit.xml',
        'views/config.xml',
    ],
    # only loaded in demonstration mode
    'demo': [
        'demo/demo.xml',
    ],
}
