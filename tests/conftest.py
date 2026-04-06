"""全局 pytest 配置."""


def pytest_addoption(parser):
    """注册自定义命令行选项."""
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="运行需要真实 LLM API 的评估测试",
    )
