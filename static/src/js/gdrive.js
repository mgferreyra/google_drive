/** @odoo-module **/

import { ActionMenus, ACTIONS_GROUP_NUMBER} from "@web/search/action_menus/action_menus";
import { patch } from "@web/core/utils/patch";
patch(ActionMenus.prototype, {

    async getActionItems(props) {
        var actionItems = await super.getActionItems(props);
        if (props.getActiveIds) {
            const [activeId] = props.getActiveIds();
            var env = this.env;
            if (env.config.viewType !== "form" || !activeId) {
                return actionItems;
            }
            const items = await this.orm.call(
                "google.drive.config",
                "get_google_drive_config",
                [props.resModel, activeId]
            );
            if (items.length) {
                items.map((item) => {
                    const googleDriveItem = {
                        key: `action-${item.name}`,
                        groupNumber: item.groupNumber || ACTIONS_GROUP_NUMBER + 1,
                        description: item.name,
                        icon: 'fa fa-link google_drive_action_item',
                        callback: () => this._onGoogleDocItemClick(item.id, activeId),
                    };
                    actionItems.push(googleDriveItem);
                });
            }
        }
        return actionItems;
    },

    /**
     * @private
     * @param {number} itemId
     * @returns {Promise}
     */
    /**async _onGoogleDocItemClick(itemId, activeId) {
            const resID = this.props.activeId;
            const domain = [['id', '=', itemId]];
            const fields = ['google_drive_resource_id', 'google_drive_client_id'];
            const configs = await this.rpc({
                args: [domain, fields],
                method: 'search_read',
                model: 'google.drive.config',
            });
            const url = await this.rpc({
                args: [itemId, resID, configs[0].google_drive_resource_id],
                context: this.props.context,
                method: 'get_google_drive_url',
                model: 'google.drive.config',
            });
            if (url) {
                window.open(url, '_blank');
            }
        }*/


    async _onGoogleDocItemClick(itemId, activeId) {
        const resID = activeId;
        const domain = [['id', '=', itemId]];
        const fields = ['google_drive_resource_id', 'google_drive_client_id'];

        const configs = await this.env.services.orm.call(
            "google.drive.config",
            "search_read",
            [domain, fields]
        );

        if (!configs.length) {
            return;
        }

        const url = await this.env.services.orm.call(
            "google.drive.config",
            "get_google_drive_url",
            [itemId, resID, configs[0].google_drive_resource_id]
        );
        if (url) {
            window.open(url, '_blank');
        }
    }

});