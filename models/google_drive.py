# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import ast
import logging
import json
import re

# Modificado para folders
import ast
# Modificado para folders

import requests
import werkzeug.urls

from odoo import api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo.tools.translate import _

from odoo.addons.google_account.models.google_service import GOOGLE_TOKEN_ENDPOINT, TIMEOUT

from datetime import date

_logger = logging.getLogger(__name__)

# Google is depreciating their OOB Auth Flow on 3rd October 2022, the Google Drive
# integration thus become irrelevant after that date.

# https://developers.googleblog.com/2022/02/making-oauth-flows-safer.html#disallowed-oob
#GOOGLE_AUTH_DEPRECATION_DATE = date(2022, 10, 3)
GOOGLE_AUTH_DEPRECATION_DATE = date(2026, 10, 3)

class GoogleDrive(models.Model):

    _name = 'google.drive.config'
    _description = "Google Drive templates config"

    
    # Dentro de la clase GoogleDrive(models.Model):

    def get_google_drive_url(self, res_id, template_id): # template_id ahora es el config_id
        if self._module_deprecated():
            return

        self.ensure_one()
        # El ID que recibimos es el de la configuración, no un template_id de Google
        config = self.sudo()

        model = config.model_id
        record = self.env[model.model].browse(res_id).read()[0]
        # ... (el resto de la preparación de 'name_gdocs' se mantiene igual)
        name_gdocs = config.name_template
        try:
            name_gdocs = name_gdocs % record
        except Exception:
            raise UserError(_("At least one key cannot be found in your Google Drive name pattern."))

        # Busca si ya existe un adjunto
        attachments = self.env["ir.attachment"].search([('res_model', '=', model.model), 
                                                        ('name', '=', name_gdocs), 
                                                        ('res_id', '=', res_id),
                                                        ('google_drive_config_id', '=', config.id)],limit=1)

        url = False
        if attachments:
            #url = attachments[0].url
            url = attachments.url
        else:
            # --- LÓGICA DE DECISIÓN ---
            if config.resource_type == 'document':
                if not config.google_drive_resource_id:
                     raise UserError(_("The template URL for this document configuration is missing or invalid."))
                # El segundo argumento es el ID del recurso de google, no el config.id
                url = self.copy_doc(res_id, config.google_drive_resource_id, name_gdocs, model.model).get('url')
            elif config.resource_type == 'folder':
                url = self.create_folder(res_id, name_gdocs, model.model).get('url')
            # --- FIN LÓGICA DE DECISIÓN ---
        return url


    def _module_deprecated(self):
        return GOOGLE_AUTH_DEPRECATION_DATE < fields.Date.today()

    @api.model
    def get_access_token(self, scope=None):
        if self._module_deprecated():
            return

        Config = self.env['ir.config_parameter'].sudo()
        google_drive_refresh_token = Config.get_param('google_drive_refresh_token')
        user_is_admin = self.env.is_admin()
        if not google_drive_refresh_token:
            if user_is_admin:
                action_id = self.env['ir.model.data']._xmlid_lookup('base_setup.action_general_configuration')[2]
                msg = _("There is no refresh code set for Google Drive. You can set it up from the configuration panel.")
                raise RedirectWarning(msg, action_id, _('Go to the configuration panel'))
            else:
                raise UserError(_("Google Drive is not yet configured. Please contact your administrator."))
        google_drive_client_id = Config.get_param('google_drive_client_id')
        google_drive_client_secret = Config.get_param('google_drive_client_secret')
        #For Getting New Access Token With help of old Refresh Token
        data = {
            'client_id': google_drive_client_id,
            'refresh_token': google_drive_refresh_token,
            'client_secret': google_drive_client_secret,
            'grant_type': "refresh_token",
            'scope': scope or 'https://www.googleapis.com/auth/drive'
        }
        headers = {"Content-type": "application/x-www-form-urlencoded"}
        try:
            req = requests.post(GOOGLE_TOKEN_ENDPOINT, data=data, headers=headers, timeout=TIMEOUT)
            req.raise_for_status()
        except requests.HTTPError:
            if user_is_admin:
                action_id = self.env['ir.model.data']._xmlid_lookup('base_setup.action_general_configuration')[2]
                msg = _("Something went wrong during the token generation. Please request again an authorization code .")
                raise RedirectWarning(msg, action_id, _('Go to the configuration panel'))
            else:
                raise UserError(_("Google Drive is not yet configured. Please contact your administrator."))
        return req.json().get('access_token')

    @api.model
    def copy_doc(self, res_id, template_id, name_gdocs, res_model):
        if self._module_deprecated():
            return

        google_web_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        access_token = self.get_access_token()
        # Copy template in to drive with help of new access token
        request_url = "https://www.googleapis.com/drive/v2/files/%s?fields=parents/id&access_token=%s" % (template_id, access_token)
        headers = {"Content-type": "application/x-www-form-urlencoded"}
        try:
            req = requests.get(request_url, headers=headers, timeout=TIMEOUT)
            req.raise_for_status()
            parents_dict = req.json()
        except requests.HTTPError:
            raise UserError(_("The Google Template cannot be found. Maybe it has been deleted."))

        record_url = "Click on link to open Record in Odoo\n %s/?db=%s#id=%s&model=%s" % (google_web_base_url, self._cr.dbname, res_id, res_model)
        data = {
            "title": name_gdocs,
            "description": record_url,
            "parents": parents_dict['parents']
        }
        request_url = "https://www.googleapis.com/drive/v2/files/%s/copy?access_token=%s" % (template_id, access_token)
        headers = {
            'Content-type': 'application/json',
            'Accept': 'text/plain'
        }
        # resp, content = Http().request(request_url, "POST", data_json, headers)
        req = requests.post(request_url, data=json.dumps(data), headers=headers, timeout=TIMEOUT)
        req.raise_for_status()
        content = req.json()
        res = {}
        if content.get('alternateLink'):
            res['id'] = self.env["ir.attachment"].create({
                'res_model': res_model,
                'name': name_gdocs,
                'res_id': res_id,
                'type': 'url',
                'url': content['alternateLink'],
                'google_drive_config_id': self.id # <-- AÑADIR ESTA LÍNEA
            }).id
            # Commit in order to attach the document to the current object instance, even if the permissions has not been written.
            self._cr.commit()
            res['url'] = content['alternateLink']
            key = self._get_key_from_url(res['url'])
            request_url = "https://www.googleapis.com/drive/v2/files/%s/permissions?emailMessage=This+is+a+drive+file+created+by+Odoo&sendNotificationEmails=false&access_token=%s" % (key, access_token)
            data = {'role': 'writer', 'type': 'anyone', 'value': '', 'withLink': True}
            try:
                req = requests.post(request_url, data=json.dumps(data), headers=headers, timeout=TIMEOUT)
                req.raise_for_status()
            except requests.HTTPError:
                raise self.env['res.config.settings'].get_config_warning(_("The permission 'reader' for 'anyone with the link' has not been written on the document"))
            if self.env.user.email:
                data = {'role': 'writer', 'type': 'user', 'value': self.env.user.email}
                try:
                    requests.post(request_url, data=json.dumps(data), headers=headers, timeout=TIMEOUT)
                except requests.HTTPError:
                    pass
        return res

    @api.model
    def get_google_drive_config(self, res_model, res_id):
        '''
        Function called by the js, when no google doc are yet associated with a record, with the aim to create one. It
        will first seek for a google.docs.config associated with the model `res_model` to find out what's the template
        of google doc to copy (this is usefull if you want to start with a non-empty document, a type or a name
        different than the default values). If no config is associated with the `res_model`, then a blank text document
        with a default name is created.
          :param res_model: the object for which the google doc is created
          :param ids: the list of ids of the objects for which the google doc is created. This list is supposed to have
            a length of 1 element only (batch processing is not supported in the code, though nothing really prevent it)
          :return: the config id and config name
        '''
        # TO DO in master: fix my signature and my model
        if isinstance(res_model, str):
            res_model = self.env['ir.model']._get_id(res_model)
        if not res_id:
            raise UserError(_("Creating google drive may only be done by one at a time."))
        # check if a model is configured with a template
        configs = self.search([('model_id', '=', res_model)])
        config_values = []
        for config in configs.sudo():
            if config.filter_id:
                if config.filter_id.user_id and config.filter_id.user_id.id != self.env.user.id:
                    #Private
                    continue
                try:
                    domain = [('id', 'in', [res_id])] + ast.literal_eval(config.filter_id.domain)
                except:
                    raise UserError(_("The document filter must not include any 'dynamic' part, so it should not be based on the current time or current user, for example."))
                additionnal_context = ast.literal_eval(config.filter_id.context)
                google_doc_configs = self.env[config.filter_id.model_id].with_context(**additionnal_context).search(domain)
                if google_doc_configs:
                    config_values.append({'id': config.id, 'name': config.name})
            else:
                config_values.append({'id': config.id, 'name': config.name})
        return config_values

    name = fields.Char('Template Name', required=True)
    model_id = fields.Many2one('ir.model', 'Model', required=True, ondelete='cascade')
    model = fields.Char('Related Model', related='model_id.model', readonly=True)
    filter_id = fields.Many2one('ir.filters', 'Filter', domain="[('model_id', '=', model)]")
    
    # --- INICIO DE MODIFICACIONES ---

    resource_type = fields.Selection([
        ('document', 'Document From Template'),
        ('folder', 'New Folder')
    ], string="Resource Type", default='document', required=True,
       help="Choose whether to create a new document by copying a template or create a new empty folder.")

    # Hacer que la URL de la plantilla no sea obligatoria, ya que no se usa para carpetas
    google_drive_template_url = fields.Char('Template URL')
    google_drive_resource_id = fields.Char('Resource Id', compute='_compute_ressource_id', store=True) # Añadir store=True para mejor rendimiento

    # Nuevo campo para la carpeta padre
    google_drive_parent_folder_url = fields.Char('Parent Folder URL', help="The URL of the Google Drive folder where new folders will be created.")
    google_drive_parent_folder_id = fields.Char('Parent Folder ID', compute='_compute_parent_folder_id', store=True)

    # --- FIN DE MODIFICACIONES ---

    
    # google_drive_template_url = fields.Char('Template URL', required=True)
    # google_drive_resource_id = fields.Char('Resource Id', compute='_compute_ressource_id')
    

    google_drive_client_id = fields.Char('Google Client', compute='_compute_client_id')
    name_template = fields.Char('Google Drive Name Pattern', default='Document %(name)s', help='Choose how the new google drive will be named, on google side. Eg. gdoc_%(field_name)s', required=True)
    active = fields.Boolean('Active', default=True)

    def _get_key_from_url(self, url):
        #word = re.search("(key=|/d/)([A-Za-z0-9-_]+)", url)
        # Modificado para aceptar /d/, /folders/ o key=
        word = re.search("(key=|/d/|/folders/)([A-Za-z0-9-_]+)", url)
        if word:
            return word.group(2)
        return None

        
    # MODIFICADO: _compute_ressource_id para que no falle si la URL está vacía
    @api.depends('google_drive_template_url')
    def _compute_ressource_id(self):
        for record in self:
            if record.google_drive_template_url:
                word = self._get_key_from_url(record.google_drive_template_url)
                if word:
                    record.google_drive_resource_id = word
                else:
                    # No lanzar un error, simplemente invalidar el campo. La validación se hará en otro lado.
                    record.google_drive_resource_id = False
            else:
                record.google_drive_resource_id = False

    # NUEVO: Función para calcular el ID de la carpeta padre
    @api.depends('google_drive_parent_folder_url')
    def _compute_parent_folder_id(self):
        for record in self:
            if record.google_drive_parent_folder_url:
                word = self._get_key_from_url(record.google_drive_parent_folder_url)
                if word:
                    record.google_drive_parent_folder_id = word
                else:
                    record.google_drive_parent_folder_id = False
            else:
                record.google_drive_parent_folder_id = False


    def _compute_client_id(self):
        google_drive_client_id = self.env['ir.config_parameter'].sudo().get_param('google_drive_client_id')
        for record in self:
            record.google_drive_client_id = google_drive_client_id

    @api.onchange('model_id')
    def _onchange_model_id(self):
        if self.model_id:
            self.model = self.model_id.model
        else:
            self.filter_id = False
            self.model = False

    @api.constrains('model_id', 'filter_id')
    def _check_model_id(self):
        for drive in self:
            if drive.filter_id and drive.model_id.model != drive.filter_id.model_id:
                raise ValidationError(_(
                    "Incoherent Google Drive %(drive)s: the model of the selected filter %(filter)r is not matching the model of current template (%(filter_model)r, %(drive_model)r)",
                    drive=drive.name, filter=drive.filter_id.name, filter_model=drive.filter_id.model_id.model, drive_model=drive.model_id.model,
                ))
        if self.model_id.model and self.filter_id:
            # force an execution of the filter to verify compatibility
            self.get_google_drive_config(self.model_id.model, 1)

    def get_google_scope(self):
        return 'https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/drive.file'

# Dentro de la clase GoogleDrive(models.Model):

    @api.model
    def create_folder(self, res_id, name_gdocs, res_model):
        # '''Creates a new folder in Google Drive.'''
        if self._module_deprecated():
            return {}

        self.ensure_one()

        if not self.google_drive_parent_folder_id:
            raise UserError(_("The parent folder is not correctly configured for this template."))

        access_token = self.get_access_token()
        google_web_base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        record_url = "Record in Odoo: %s/?db=%s#id=%s&model=%s" % (google_web_base_url, self._cr.dbname, res_id, res_model)

        # Datos para la API de Google Drive v2 para crear una carpeta
        data = {
            "title": name_gdocs,
            "description": record_url,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [{"id": self.google_drive_parent_folder_id}]
        }
        
        request_url = "https://www.googleapis.com/drive/v2/files?access_token=%s" % access_token
        headers = {'Content-Type': 'application/json'}
        
        try:
            req = requests.post(request_url, data=json.dumps(data), headers=headers, timeout=TIMEOUT)
            req.raise_for_status()
            content = req.json()
        except requests.HTTPError as e:
            _logger.error("Error creating Google Drive folder: %s", e.response.text)
            raise UserError(_("Could not create the Google Drive folder. Check your configuration and permissions."))

        res = {}
        if content.get('alternateLink'):
            # Crear el adjunto en Odoo
            self.env["ir.attachment"].create({
                'res_model': res_model,
                'name': name_gdocs,
                'res_id': res_id,
                'type': 'url',
                'url': content['alternateLink'],
                'google_drive_config_id': self.id # <-- AÑADIR ESTA LÍNEA
            })
            self._cr.commit()
            res['url'] = content['alternateLink']
        
        return res



