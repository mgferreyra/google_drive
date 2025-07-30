from odoo import fields, models

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    google_drive_config_id = fields.Many2one(
        'google.drive.config', 
        string="Google Drive Config",
        help="The Google Drive configuration that generated this attachment.",
        ondelete='set null' # Para no borrar el adjunto si se borra la plantilla
    )