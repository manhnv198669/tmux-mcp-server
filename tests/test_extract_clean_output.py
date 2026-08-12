"""Pure unit tests for extract_clean_output covering all 3 execution branches."""

from tmux_mcp.exec.engine import extract_clean_output


def test_branch_1_both_markers_present():
    cmd_id = "cmd_test123"
    raw_text = (
        "printf '%s\\n' '__TMUX_MCP_START_cmd_test123__'; echo HI\n"
        "\x1b[33m\x1b[0mmanh@macbook % \x1b[0m\n"
        "__TMUX_MCP_START_cmd_test123__\n"
        "Hello World 1\n"
        "Hello World 2\n"
        "__TMUX_MCP_END_cmd_test123__\n"
        "manh@macbook % \n"
    )

    clean_output, truncated = extract_clean_output(raw_text, cmd_id)
    assert clean_output == "Hello World 1\nHello World 2"
    assert not truncated


def test_branch_2_start_marker_only_running_or_timeout():
    cmd_id = "cmd_test456"
    raw_text = (
        "printf '%s\\n' '__TMUX_MCP_START_cmd_test456__'; sleep 20\n"
        "manh@macbook % \n"
        "__TMUX_MCP_START_cmd_test456__\n"
        "PARTIAL_LINE_1\n"
        "PARTIAL_LINE_2\n"
    )

    clean_output, truncated = extract_clean_output(raw_text, cmd_id)
    assert clean_output == "PARTIAL_LINE_1\nPARTIAL_LINE_2"
    assert not truncated
    assert "wait-for" not in clean_output
    assert "rc.txt" not in clean_output


def test_branch_3_no_start_marker_returns_empty():
    cmd_id = "cmd_test789"
    raw_text = (
        "manh@macbook % printf '%s\\n' '__TMUX_MCP_START_cmd_test789__'\n"
        "some random output before execution\n"
    )

    clean_output, truncated = extract_clean_output(raw_text, cmd_id)
    assert clean_output == ""
    assert not truncated
