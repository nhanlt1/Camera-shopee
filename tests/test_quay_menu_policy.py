from packrecorder.ui.quay_menu_policy import should_show_top_level_search_action


def test_search_action_hidden_when_tabs_exist():
    assert should_show_top_level_search_action(has_management_tab=True) is False


def test_search_action_shown_without_tabs():
    assert should_show_top_level_search_action(has_management_tab=False) is True
