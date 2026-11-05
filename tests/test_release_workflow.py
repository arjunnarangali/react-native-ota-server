from uuid import UUID, uuid4


def publish(client, bundle, *, channel="production", rollout=100, token="test-admin-token"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with bundle.bundle_path.open("rb") as artifact:
        return client.post(
            "/api/v1/admin/releases",
            headers=headers,
            data={
                "manifest": bundle.manifest_bytes.decode("utf-8"),
                "signature": bundle.signature,
                "channel": channel,
                "rollout_percentage": str(rollout),
            },
            files={"bundle": (bundle.bundle_path.name, artifact, "application/zip")},
        )


def update_check(
    client,
    *,
    version=0,
    app_id="com.ota",
    runtime="rn-0.88.0-android-1",
    channel="production",
    failed_release_id=None,
    platform="android",
):
    payload = {
            "platform": platform,
            "app_id": app_id,
            "runtime_version": runtime,
            "channel": channel,
            "current_version": version,
            "installation_id": str(uuid4()),
        }
    if failed_release_id is not None:
        payload["failed_release_id"] = failed_release_id
    return client.post(
        "/api/v1/updates/check",
        json=payload,
    )


def test_publish_update_check_and_download(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    bundle = signed_bundle_factory(1)

    published = publish(client, bundle)
    assert published.status_code == 201, published.text
    assert published.json()["state"] == "active"

    check = update_check(client)
    assert check.status_code == 200
    payload = check.json()
    assert payload["update_available"] is True
    assert payload["release"]["manifest"]["version"] == 1
    assert payload["release"]["action"] == "update"

    download = client.get(payload["release"]["download_url"])
    assert download.status_code == 200
    assert download.content == bundle.bundle_path.read_bytes()


def test_admin_authentication_is_required(release_environment, signed_bundle_factory):
    response = publish(
        release_environment["client"],
        signed_bundle_factory(1),
        token=None,
    )

    assert response.status_code == 401


def test_signature_and_artifact_hash_are_verified(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    bundle = signed_bundle_factory(1)

    invalid_signature = type(bundle)(
        bundle.bundle_path, bundle.manifest_bytes, "invalid-signature", bundle.release_id
    )
    assert publish(client, invalid_signature).status_code == 400

    original_size = bundle.bundle_path.stat().st_size
    bundle.bundle_path.write_bytes(b"x" * original_size)
    mismatch = publish(client, bundle)
    assert mismatch.status_code == 400
    assert "hash does not match" in mismatch.json()["detail"]


def test_rollout_and_runtime_compatibility(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    published = publish(client, signed_bundle_factory(1), rollout=0)
    release_id = published.json()["release_id"]

    assert update_check(client).json()["update_available"] is False
    assert update_check(client, runtime="different-native-runtime").json()["update_available"] is False

    changed = client.patch(
        f"/api/v1/admin/releases/{release_id}/rollout",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"rollout_percentage": 100},
    )
    assert changed.status_code == 200
    assert update_check(client).json()["update_available"] is True


def test_rollback_delivers_previous_release_as_downgrade(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    first = publish(client, signed_bundle_factory(1)).json()
    second = publish(client, signed_bundle_factory(2)).json()
    releases = client.get(
        "/api/v1/admin/releases",
        headers={"Authorization": "Bearer test-admin-token"},
    ).json()
    assert {item["release_id"]: item["state"] for item in releases} == {
        first["release_id"]: "archived",
        second["release_id"]: "active",
    }

    rollback = client.post(
        f"/api/v1/admin/releases/{first['release_id']}/rollback",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["is_rollback"] is True
    releases_after_rollback = client.get(
        "/api/v1/admin/releases",
        headers={"Authorization": "Bearer test-admin-token"},
    ).json()
    assert {item["release_id"]: item["state"] for item in releases_after_rollback} == {
        first["release_id"]: "active",
        second["release_id"]: "archived",
    }

    check = update_check(client, version=2).json()
    assert check["update_available"] is True
    assert check["release"]["manifest"]["version"] == 1
    assert check["release"]["action"] == "rollback"


def test_disabled_release_is_not_offered_or_downloadable(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    published = publish(client, signed_bundle_factory(1)).json()
    disabled = client.post(
        f"/api/v1/admin/releases/{published['release_id']}/disable",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert disabled.status_code == 200
    assert update_check(client).json()["update_available"] is False
    assert client.get(f"/api/v1/releases/{published['release_id']}/bundle").status_code == 404


def test_client_can_suppress_a_release_that_failed_startup(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    published = publish(client, signed_bundle_factory(1)).json()

    check = update_check(client, failed_release_id=published["release_id"])

    assert check.status_code == 200
    assert check.json() == {"update_available": False, "release": None}


def test_update_response_can_use_configured_public_origin(release_environment, signed_bundle_factory):
    environment = release_environment
    environment["settings"].ota_public_base_url = "https://ota-example.ngrok.app"
    published = publish(environment["client"], signed_bundle_factory(1))
    assert published.status_code == 201

    check = update_check(environment["client"]).json()

    assert check["release"]["download_url"].startswith(
        "https://ota-example.ngrok.app/api/v1/releases/"
    )


def test_ios_release_and_android_release_are_isolated(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    lane = {
        "app_id": "com.ota.shared",
        "runtime_version": "rn-0.88.0-ios-v1",
    }
    ios_bundle = signed_bundle_factory(1, platform="ios", **lane)
    android_bundle = signed_bundle_factory(1, platform="android", **lane)

    ios_published = publish(client, ios_bundle, channel="development")
    android_published = publish(client, android_bundle, channel="development")

    assert ios_published.status_code == 201, ios_published.text
    assert android_published.status_code == 201, android_published.text
    ios_check = update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        platform="ios", channel="development",
    )
    android_check = update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        platform="android", channel="development",
    )
    assert ios_check.json()["release"]["manifest"]["platform"] == "ios"
    assert android_check.json()["release"]["manifest"]["platform"] == "android"
    assert ios_check.json()["release"]["manifest"]["version"] == 1
    assert android_check.json()["release"]["manifest"]["version"] == 1
    ios_download = client.get(ios_check.json()["release"]["download_url"])
    assert ios_download.status_code == 200
    assert ios_download.content == ios_bundle.bundle_path.read_bytes()

    duplicate_android_version = publish(
        client,
        signed_bundle_factory(1, platform="android", **lane),
        channel="development",
    )
    assert duplicate_android_version.status_code == 409


def test_update_check_rejects_other_platform_and_unknown_platform(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    ios_bundle = signed_bundle_factory(
        1,
        platform="ios",
        app_id="com.ota.ios",
        runtime_version="rn-0.88-ios-v1",
    )
    published = publish(client, ios_bundle, channel="development")
    assert published.status_code == 201, published.text

    android_check = update_check(
        client,
        app_id="com.ota.ios",
        runtime="rn-0.88-ios-v1",
        channel="development",
        platform="android",
    )
    assert android_check.status_code == 200
    assert android_check.json() == {"update_available": False, "release": None}

    invalid_platform = client.post(
        "/api/v1/updates/check",
        json={
            "platform": "tvos",
            "app_id": "com.ota.ios",
            "runtime_version": "rn-0.88-ios-v1",
            "channel": "development",
            "current_version": 0,
            "installation_id": str(uuid4()),
        },
    )
    assert invalid_platform.status_code == 422


def test_admin_rollback_is_scoped_to_its_platform_lane(release_environment, signed_bundle_factory):
    client = release_environment["client"]
    lane = {"app_id": "com.ota.sharedadmin", "runtime_version": "rn-0.88-shared"}
    ios_v1 = publish(client, signed_bundle_factory(1, platform="ios", **lane), channel="development").json()
    publish(client, signed_bundle_factory(2, platform="ios", **lane), channel="development")
    publish(client, signed_bundle_factory(1, platform="android", **lane), channel="development")
    android_v2 = publish(client, signed_bundle_factory(2, platform="android", **lane), channel="development").json()

    rollback = client.post(
        f"/api/v1/admin/releases/{ios_v1['release_id']}/rollback",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["manifest"]["platform"] == "ios"

    ios_check = update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="ios", version=2,
    )
    android_check = update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="android", version=1,
    )
    assert ios_check.json()["release"]["manifest"]["version"] == 1
    assert ios_check.json()["release"]["action"] == "rollback"
    assert android_check.json()["release"]["manifest"]["release_id"] == android_v2["release_id"]

    changed_rollout = client.patch(
        f"/api/v1/admin/releases/{ios_v1['release_id']}/rollout",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"rollout_percentage": 0},
    )
    assert changed_rollout.status_code == 200
    assert update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="ios", version=2,
    ).json()["update_available"] is False
    assert update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="android", version=1,
    ).json()["release"]["manifest"]["release_id"] == android_v2["release_id"]

    client.patch(
        f"/api/v1/admin/releases/{ios_v1['release_id']}/rollout",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"rollout_percentage": 100},
    )

    disabled = client.post(
        f"/api/v1/admin/releases/{ios_v1['release_id']}/disable",
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert disabled.status_code == 200
    assert update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="ios", version=2,
    ).json()["update_available"] is False
    assert update_check(
        client, app_id=lane["app_id"], runtime=lane["runtime_version"],
        channel="development", platform="android", version=1,
    ).json()["release"]["manifest"]["release_id"] == android_v2["release_id"]


def test_publish_rejects_source_package_even_when_signed(release_environment, signed_bundle_factory):
    environment = release_environment
    source_bundle = signed_bundle_factory(
        1,
        platform="ios",
        app_id="com.ota.iossource",
        runtime_version="rn-0.88-ios-v1",
        bundle_format="javascript-source",
    )

    response = publish(environment["client"], source_bundle, channel="development")

    assert response.status_code == 400
    assert "Hermes bytecode" in response.json()["detail"]
    assert not environment["storage"].artifact_path(UUID(source_bundle.release_id)).exists()


def test_openapi_lists_supported_platform_values(release_environment):
    schema = release_environment["client"].get("/openapi.json").json()

    manifest_platforms = schema["components"]["schemas"]["ReleaseManifest"]["properties"]["platform"]["enum"]
    request_platforms = schema["components"]["schemas"]["UpdateCheckRequest"]["properties"]["platform"]["enum"]
    assert manifest_platforms == ["android", "ios"]
    assert request_platforms == ["android", "ios"]
