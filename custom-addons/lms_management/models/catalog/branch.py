from odoo import models, fields

from odoo.exceptions import UserError


class ResBranch(models.Model):
    _inherit = "res.branch"

    lounge_id = fields.Many2one(comodel_name="lms.lounge", string="Lounge", required=False, ondelete="restrict" , tracking=True)

    def create_lounge(self):
        """ Create Lounge With Branch Data"""
        try:
            for rec in self:
                if not rec.lounge_id:
                    vals = {
                        'branch_id': rec.id,
                        'name': rec.name,
                        'code': rec.code,
                    }
                    lounge = self.env['lms.lounge'].create(vals)
                    rec.lounge_id = lounge.id
        except Exception as e:
            raise UserError(f"Something we wrong:\n{str(e)}")
