import pytest

from arbiter.config import Settings


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_dev_secrets_refused_outside_dev(env):
    with pytest.raises(RuntimeError, match="SECRETS_KEY|JWT_SECRET"):
        Settings(env=env).assert_deployable()


def test_real_secrets_accepted():
    Settings(env="prod", jwt_secret="x" * 40, secrets_key="y" * 40).assert_deployable()
    Settings(env="dev").assert_deployable()
