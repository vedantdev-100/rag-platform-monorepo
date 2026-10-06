"""Patch only the Settings flag and supplied main.py consumer registration.

Refuse an unrecognized startup layout instead of overwriting custom app code.
No dependencies or database connection are needed to execute this script.
"""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config_path = root / "services/rag-service/app/core/config.py"
main_path = root / "services/rag-service/app/main.py"
config = config_path.read_text(encoding="utf-8")
main = main_path.read_text(encoding="utf-8")
flag = '    RUN_LIFECYCLE_CONSUMER: bool = True'
if 'RUN_LIFECYCLE_CONSUMER:' not in config:
    tree = ast.parse(config)
    settings = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Settings'), None)
    if settings is None:
        raise SystemExit('Settings class not found; no files changed.')
    target = next((node for node in settings.body if isinstance(node, ast.AnnAssign)
                   and isinstance(node.target, ast.Name) and node.target.id == 'USER_EVENTS_CONSUMER_GROUP'), None)
    if target is None:
        raise SystemExit('USER_EVENTS_CONSUMER_GROUP field not found; no files changed.')
    lines = config.splitlines(keepends=True)
    lines.insert(target.end_lineno, flag + '\n')
    config = ''.join(lines)

if 'if settings.RUN_LIFECYCLE_CONSUMER:' not in main:
    tree = ast.parse(main)
    create_app = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'create_app'), None)
    if create_app is None:
        raise SystemExit('create_app function not found. Send current main.py; no files changed.')
    nodes = create_app.body
    index = next((i for i, node in enumerate(nodes) if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == 'consumer' for target in node.targets)), None)
    if index is None or len(nodes) <= index + 2:
        raise SystemExit('Expected consumer registration not found. Send current main.py; no files changed.')
    first, startup, shutdown = nodes[index:index + 3]
    if not (isinstance(startup, ast.AsyncFunctionDef) and startup.name == '_start_consumer'
            and isinstance(shutdown, ast.AsyncFunctionDef) and shutdown.name == '_stop_consumer'
            and isinstance(first.value, ast.Call) and isinstance(first.value.func, ast.Name)
            and first.value.func.id == 'UserEventConsumer'):
        raise SystemExit('Consumer registration differs from the supplied version. Send current main.py; no files changed.')
    # Verify the hooks are still the original small functions. Do not erase
    # custom startup/shutdown work added since the upload.
    expected = ast.parse("""
async def start():
    app.state.consumer_task = asyncio.create_task(consumer.run())
async def stop():
    await consumer.stop()
    app.state.consumer_task.cancel()
""")
    def signature(body):
        return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)
    if (signature(startup.body) != signature(expected.body[0].body)
            or signature(shutdown.body) != signature(expected.body[1].body)):
        raise SystemExit('Startup/shutdown hooks have custom changes. Send current main.py; no files changed.')
    expected_call = ast.parse('UserEventConsumer(settings.REDIS_URL, settings.USER_EVENTS_STREAM, settings.USER_EVENTS_CONSUMER_GROUP)', mode='eval').body
    if ast.dump(first.value, include_attributes=False) != ast.dump(expected_call, include_attributes=False):
        raise SystemExit('Consumer configuration has custom changes. Send current main.py; no files changed.')
    replacement = '''    if settings.RUN_LIFECYCLE_CONSUMER:
        consumer = UserEventConsumer(
            settings.REDIS_URL, settings.USER_EVENTS_STREAM, settings.USER_EVENTS_CONSUMER_GROUP,
        )

        @app.on_event("startup")
        async def _start_consumer():
            app.state.consumer_task = asyncio.create_task(consumer.run())

        @app.on_event("shutdown")
        async def _stop_consumer():
            app.state.consumer_task.cancel()
            await asyncio.gather(app.state.consumer_task, return_exceptions=True)
            await consumer.stop()
    else:
        logger.info("api_background_consumers_disabled")
'''
    lines = main.splitlines(keepends=True)
    main = ''.join(lines[:first.lineno - 1]) + replacement + ''.join(lines[shutdown.end_lineno:])

ast.parse(config)
ast.parse(main)
# Validate both candidates before either file is written.
config_path.write_text(config, encoding="utf-8")
main_path.write_text(main, encoding="utf-8")
print('Step 8 applied: API consumer can be disabled; existing routes and settings retained.')
