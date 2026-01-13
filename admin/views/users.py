# ruff: noqa: RUF012
from flask_admin.contrib.sqla import ModelView


class UserView(ModelView):
    can_delete = True
    can_create = False
    can_edit = True
    can_view_details = True
    edit_modal = True
    can_export = True
    details_modal = True
    export_types = ["csv", "xlsx", "json", "yaml"]

    column_searchable_list = ["id", "full_name"]
    column_filters = ["is_admin", "is_authenticated", "notification_enabled", "group_name", "created_at"]
    column_list = [
        "id",
        "full_name",
        "language_code",
        "is_admin",
        "is_authenticated",
        "notification_enabled",
        "group_name",
        "created_at",
    ]
    column_default_sort = ("created_at", True)
