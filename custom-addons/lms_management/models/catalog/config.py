# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    lounge_access_product_id = fields.Many2one('product.product', 'Lounge Access Product',
                                               config_parameter='lounge_access_product_id', ondelete="restrict")
    cash_partner_id = fields.Many2one('res.partner', 'Cash Partner', config_parameter='cash_partner_id', ondelete="restrict")

    voucher_product_id = fields.Many2one('product.product', 'Voucher Product', config_parameter='voucher_product_id', ondelete="restrict")
    hayyak_voucher_product_id = fields.Many2one('product.product', 'Hayyak Voucher Product',
                                                config_parameter='hayyak_voucher_product_id', ondelete="restrict")

    create_before = fields.Float(string="Allow Creation Before", required=False, default=8.5)
    expire_after = fields.Float(string="Draft Expire After", required=False, config_parameter='expire_after')

    @api.constrains('create_before')
    def _check_create_before(self):
        if self.create_before < 0:
            raise UserError(_('Create Before must be a positive number'))
