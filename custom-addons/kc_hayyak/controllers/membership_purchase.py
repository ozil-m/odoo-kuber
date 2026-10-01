# -*- coding: utf-8 -*-
from odoo import http, fields, api, fields, SUPERUSER_ID
from odoo.http import request
import threading
import odoo
import logging

_logger = logging.getLogger(__name__)


class MembershipPurchaseController(http.Controller):


    @http.route('/hayyak_app/tier_create', type="json", auth='bearer', methods=["POST"], csrf=False, cors='*')
    def tier_create(self, tierName, tierID):
        """Create a new membership tier."""
        try:
            env = request.env
            # ✅ Check if a product with the same barcode already exists
            existing_product = env['product.product'].sudo().search(
                ['|', ('barcode', '=', tierID), ('name', '=', tierName)], limit=1)
            if existing_product:
                return {
                    'code': 409,
                    'message': f'Tier with the same ID or name already exists.',
                    'data': {'lmsTierId': existing_product.id, 'ScTierID': existing_product.barcode,
                             'tierName': existing_product.name}
                }

            # Get category ID from system parameters
            tiers_category_id = env['ir.config_parameter'].sudo().get_param('tiers_category_id')
            category = False

            if tiers_category_id:
                category = env['product.category'].sudo().browse(int(tiers_category_id))
                if not category.exists():
                    category = False

            # If no valid category found, fallback to any available category
            if not category:
                category = env['product.category'].sudo().search([], limit=1)
                if not category:
                    return {'code': 400, 'message': 'No product category found to assign the tier.'}

            _logger.info(f"category ********************************** {category}")

            product = env['product.product'].sudo().create({
                'name': tierName,
                'barcode': tierID,
                'categ_id': category.id,
                'type': 'service',
                'invoice_policy': 'order',
                'sale_ok': True,
                'purchase_ok': False,
            })

            _logger.info(f"session_info ********************************** {product}")
            result = {"tierId": product.id, "tierName": product.name, }
            return {'code': 200, 'data': result, 'message': 'Tier created successfully.'}

        except Exception as e:
            return {"code": 500, "status": "error", "message": str(e)}


    @http.route('/hayyak_app/membership_purchase', type="json", auth='bearer', methods=["POST"], csrf=False, cors='*')
    def membership_purchase(self, lmsTierId, tierPrice, subscriberId, purchaseDate, sourceId):
        """Handle membership purchase requests."""
        try:
            env = request.env

            # Validate product
            product = env['product.product'].sudo().browse(int(lmsTierId))
            if not product.exists():
                return {"code": 400, "message": "Invalid tierId provided.", "data": []}

            # Validate partner
            partner = env['res.partner'].sudo().search([('ref', '=', subscriberId)], limit=1)
            if not partner:
                return {"code": 400, "message": "Invalid subscriberId provided.", "data": []}

            purchase_date = purchaseDate.replace('T', ' ') if purchaseDate else fields.Datetime.now()

            # Create the sale order
            sale_order = env['sale.order'].sudo().create({
                'partner_id': partner.id,
                'date_order': purchase_date,
                'moyasar_payment_ref': sourceId,
                'hayyak_app': True,
                'order_line': [
                    (0, 0, {
                        'product_id': product.id,
                        'product_uom_qty': 1,
                        'price_unit': tierPrice,
                    })
                ]
            })
            env.cr.commit()
            result = {"order_id": sale_order.id, "order_name": sale_order.name}
            response = {
                'code': 200,
                'data': result,
                'message': 'Membership purchase received. Your E-Invoice will be sent to your registered email shortly.'
            }

            # ✅ Define background task properly
            def process_sale_order(db_name, sale_order_id, product_name):
                """Process the sale order in a new thread-safe Odoo environment."""
                _logger.info("Processing sale order %s in background thread.", sale_order_id)
                try:
                    with odoo.api.Environment.manage():
                        registry = odoo.registry(db_name)
                        with registry.cursor() as cr:
                            env = api.Environment(cr, SUPERUSER_ID, {})
                            sale_order = env['sale.order'].browse(sale_order_id)

                            if not sale_order.exists():
                                _logger.error("Sale order %s not found.", sale_order_id)
                                return

                            sale_order.action_set_accounting_data()
                            sale_order.action_confirm()
                            sale_order._create_invoices()
                            sale_order.action_create_payments(product_name)
                            cr.commit()
                            _logger.info("Successfully processed sale order %s", sale_order_id)

                except Exception as e:
                    _logger.error("Failed to process sale order %s: %s", sale_order_id, str(e))

            # ✅ Launch background processing with proper environment
            threading.Thread(
                target=process_sale_order,
                args=(env.cr.dbname, sale_order.id, product.name),
                daemon=True
            ).start()

            return response

        except Exception as e:
            _logger.exception("Error in membership_purchase: %s", str(e))
            return {"code": 500, "status": "error", "message": str(e)}
