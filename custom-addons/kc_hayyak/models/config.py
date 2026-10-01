# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sc_api_url = fields.Char(string="SC API URL", required=True, config_parameter='sc_api_url')
    tiers_category_id = fields.Many2one(comodel_name="product.category", string="Hayyak Tiers Category", required=False,
                                        ondelete='restrict', config_parameter='tiers_category_id', )
    membership_account_department_id = fields.Many2one(comodel_name="account.department", string="Account Department",
                                                  required=False, ondelete='restrict',
                                                  config_parameter='membership_account_department_id', )
    membership_analytic_id = fields.Many2one(comodel_name="account.analytic.account", string="Analytic Account",
                                        config_parameter='membership_analytic_id', ondelete='restrict', )
