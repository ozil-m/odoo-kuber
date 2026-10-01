from odoo import http, _
import base64


class LMSAttachmentApi(http.Controller):

    @http.route(['/attachment/read', '/attachment/search'], type="bearer", auth="user", methods=['POST', 'GET'],
                csrf=False, cors='*')
    def attachment_read(self, visit_id):
        """ Get attachment list by visit ID"""
        result = []
        base_url = http.request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        model = 'lms.visit'
        try:
            attachment = http.request.env['ir.attachment']
            visit = http.request.env[model].browse(int(visit_id))
            if not visit.exists():
                return {'code': 404, 'data': [], 'message': _('Visit ID not found')}
            attachment_ids = attachment.search(
                [('res_model', '=', model), ('res_id', '=', visit_id)])
            if attachment_ids:
                for attach in attachment_ids:
                    if attach.public and base_url:
                        url = f"{base_url}/web/content/{attach.id}"
                        result.append(
                            {
                                'id': attach.id,
                                'name': attach.name,
                                'create_by': {'id': attach.create_uid.id,
                                              'name': attach.create_uid.name} if attach.create_uid else None,
                                "create_date": attach.create_date and attach.create_date.isoformat() or None,
                                'url': url,
                            }
                        )

            return {'code': 202, 'data': result, 'message': _('Successfully')}
        except Exception as e:
            return {'code': 500, 'data': [], 'message': e}

    @http.route(['/attachment/create'], type="bearer", auth="user", methods=['POST'], csrf=False, cors='*')
    def create_attachment(self, **kw):
        """ Create attachment for visit ID"""
        visit_id = kw.get('visit_id', False)
        attachment_files = kw.get('attachments', [])
        model = 'lms.visit'
        attachment = http.request.env['ir.attachment']
        if not visit_id:
            return {'code': 404, 'data': [], 'message': _('Please add visit ID to create attachment')}
        if not attachment_files:
            return {'code': 404, 'data': [], 'message': _('Please add attachment files to create')}
        try:
            visit = http.request.env[model].browse(int(visit_id))
            if not visit.exists():
                return {'code': 404, 'data': [], 'message': _('Visit ID not found')}
            for attachment_file in attachment_files:
                attachment_data = base64.b64decode(attachment_file['attachment'])
                if attachment_data:
                    vals = {
                        'res_name': attachment_file['name'],
                        'res_model': model,
                        'res_id': visit_id,
                        'datas': base64.b64encode(attachment_data),
                        'type': 'binary',
                        'public': True,
                        'name': attachment_file['name'],
                    }
                    data = attachment.create(vals)
            return {'code': 202, 'message': _('Successfully Added')}
        except Exception as e:
            return {'code': 500, 'data': [], 'message': e}

    @http.route(['/attachment/remove'], type="json", auth="user", methods=['POST'], csrf=False, cors='*')
    def remove_attachment(self, **kw):
        """ Remove attachment by attachment ID"""
        attachment_id = kw.get('attachment_id', False)
        try:
            attachment = http.request.env['ir.attachment']
            if not attachment_id:
                return {'code': 404, 'data': [], 'message': _('Please add attachment ID to remove')}
            attachment_file = attachment.browse(attachment_id)
            name = attachment_file.name
            unlink = attachment_file.unlink()
            if unlink:
                return {'code': 202, 'data': [], 'message': _(f'Successfully remove {name}')}
        except Exception as e:
            return {'code': 500, 'data': [], 'message': e}
