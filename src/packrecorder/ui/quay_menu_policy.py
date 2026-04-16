"""Policy helper for top-level Quay menu actions."""


def should_show_top_level_search_action(*, has_management_tab: bool) -> bool:
    return not has_management_tab
