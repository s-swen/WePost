# ═══════════════════════════════════════════════════════════════════
# 🏗️ STEP 1 — BUILD STAGE: PREPARE THE APPLICATION ENVIRONMENT
# ═══════════════════════════════════════════════════════════════════

# BUILD STAGE
# └─ 🏷️ A human-readable section label, NOT a Docker instruction.
#    It separates the build environment from the production environment
#    below. Docker itself does not interpret this comment.

FROM python:3.14.4-slim-bookworm AS builder
# │    │                               │
# │    │                               └─ 🏷️ AS builder gives this stage
# │    │                                  a name so later instructions
# │    │                                  can refer to it with
# │    │                                  COPY --from=builder.
# │    │                                  This is a MULTI-STAGE BUILD:
# │    │                                  builder artifacts can be copied
# │    │                                  into a separate final image.
# │    │
# │    └─ 🐍 python:3.14.4-slim-bookworm:
# │       • python: official Python image family.
# │       • 3.14.4: exact Python patch version requested.
# │       • slim: smaller Debian-based image with fewer packages.
# │       • bookworm: Debian 12 release codename.
# │       Pinning the version improves reproducibility, but the tag
# │       alone does not guarantee immutable image contents. 🔒
# │
# └─ 🏁 FROM starts a new build stage and selects its base filesystem.
#    The builder has Python available for creating the virtual
#    environment and installing the project's dependencies.


# Copy UV binary from official image
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/
# │         │                                   │   │   │
# │         │                                   │   │   └─ 📁 /bin/ is
# │         │                                   │      the destination
# │         │                                   │      directory inside
# │         │                                   │      the builder image.
# │         │                                   │      Both binaries are
# │         │                                   │      copied there.
# │         │                                   │
# │         │                                   │   └─ ⚡ /uvx is uv's
# │         │                                   │      tool-execution
# │         │                                   │      interface.
# │         │                                   │      It is copied even
# │         │                                   │      if this Dockerfile
# │         │                                   │      never calls it.
# │         │                                   │
# │         │                                   └─ 📦 /uv is the main
# │         │                                      Astral uv executable,
# │         │                                      used below for
# │         │                                      dependency management.
# │         │
# │         └─ 🔗 --from= selects a SOURCE IMAGE, not a previous stage.
# │            ghcr.io/astral-sh/uv:0.11.6 is the image reference.
# │            Docker copies only the requested files, rather than
# │            installing uv through pip or copying its entire image.
# │
# └─ 💡 WHY THIS MATTERS:
#    uv is a separate Rust-based Python package/project manager.
#    This approach avoids a separate installation step for uv.
#    The uv binary is needed in the BUILDER, but the final stage
#    does not need to contain it. 📦


WORKDIR /app
# │       └─ 📁 Sets /app as the working directory for subsequent
# │          Dockerfile instructions in THIS stage.
# │          Relative paths such as COPY destinations and commands
# │          are interpreted in relation to this directory where
# │          applicable.
# └─ 🧭 WORKDIR is not merely a shell `cd`: Docker persists the
#    configured working directory for later instructions.
#    The production stage will need its own WORKDIR because a new
#    FROM starts a fresh stage.


# ═══════════════════════════════════════════════════════════════════
# ⚡ STEP 2 — UV SETTINGS: CONTROL HOW DEPENDENCIES ARE INSTALLED
# ═══════════════════════════════════════════════════════════════════

# UV Docker optimizations
# └─ 🏷️ Comment only. The following ENV instructions configure uv's
#    behavior while Docker builds this stage.

ENV UV_COMPILE_BYTECODE=1
# │   │                  └─ 🔢 Enables Python bytecode compilation
# │   │                     during uv installation/synchronization.
# │   │                     Python can use compiled .pyc files instead
# │   │                     of compiling source into bytecode on the
# │   │                     first import, potentially improving startup.
# │   │                     It does NOT compile Python into native
# │   │                     machine code. 🐍
# │   │
# └─ ⚙️ ENV sets an environment variable in the image configuration.
#    uv recognizes this variable and changes its behavior accordingly.
#    Unlike a shell-local variable, Docker ENV persists into later
#    instructions and the resulting stage's image configuration.


ENV UV_LINK_MODE=copy
# │   │             └─ 📋 Tells uv to COPY package files into the
# │   │                destination environment rather than attempting
# │   │                hardlinks or other linking methods.
# │   │                This is useful in Docker because uv's cache
# │   │                and /app/.venv may live on different filesystems
# │   │                or mount boundaries.
# │   │
# └─ ⚡ WHY: hardlinks require compatible filesystem boundaries.
#    Copying is more reliable when the cache and virtual environment
#    cannot share hardlinks. The trade-off is extra file copying.


ENV UV_PYTHON_DOWNLOADS=0
# │   │                    └─ 🛑 Disables uv's automatic downloading
# │   │                       of Python interpreter installations.
# │   │                       The official Python base image already
#   │                       supplies Python, so downloading another
#   │                       interpreter would normally be unnecessary.
# │
# └─ 🔗 INTERDEPENDENCY:
#    FROM python:3.14.4-slim-bookworm provides the Python interpreter.
#    UV_PYTHON_DOWNLOADS=0 tells uv not to fetch a separate one.
#    Together, they help uv use the Python installation already present.
#    ⚠️ This setting does not install Python or select every Python
#    compatibility constraint automatically.


# ═══════════════════════════════════════════════════════════════════
# 📦 STEP 3 — INSTALL DEPENDENCIES FIRST FOR DOCKER LAYER CACHING
# ═══════════════════════════════════════════════════════════════════

# Install dependencies first (cached if unchanged)
COPY pyproject.toml uv.lock ./
# │    │             │         │       │
# │    │             │         │       └─ 📁 Destination: the current
# │    │             │         │          WORKDIR, /app.
# │    │             │         │          `./` means the current directory.
# │    │             │         │
# │    │             │         └─ 🔒 uv.lock records the resolved
# │    │             │            dependency versions and related
# │    │             │            package information.
# │    │             │            It helps reproduce the same
# │    │             │            dependency resolution.
# │    │             │
# │    │             └─ 📝 pyproject.toml declares project metadata,
# │    │                dependency requirements, build configuration,
# │    │                and possibly Python-version constraints.
# │    │
# │    └─ 🚚 COPY transfers files from the Docker BUILD CONTEXT
# │       into the image filesystem.
# │
# └─ ⚡ THE CACHE STRATEGY:
#    Dependency manifests change less often than application source.
#    By copying these files first, Docker can reuse the dependency
#    installation layer after ordinary code edits.
#    ⚠️ This assumes the dependency inputs used by uv are all copied
#    before the installation step. Local path dependencies or other
#    required files may need to be copied earlier, too.


RUN uv sync --locked --no-install-project --no-dev
# │   │  │   │       │        │                   │
# │   │  │   │       │        │                   └─ 🚫 Excludes
# │   │  │   │       │        │                      development-only
# │   │  │   │       │        │                      dependency groups.
# │   │  │   │       │        │                      These can include
# │   │  │   │       │        │                      pytest and linters.
# │   │  │   │       │        │                      Exact group behavior
# │   │  │   │       │        │                      depends on the
# │   │  │   │       │        │                      project's uv config.
# │   │  │   │       │        │
# │   │  │   │       │        └─ 📦 --no-install-project tells uv NOT
# │   │  │   │       │           to install the root project itself yet.
# │   │  │   │       │           Its source code has not been copied
# │   │  │   │       │           into /app at this point.
# │   │  │   │       │           External dependencies can be installed
# │   │  │   │       │           without installing the application.
# │   │  │   │       │
# │   │  │   │       └─ 🔒 --locked requires uv to respect uv.lock.
# │   │  │   │          If the lockfile needs updating to agree with
# │   │  │   │          the project configuration, the command fails
# │   │  │   │          rather than silently rewriting the lockfile.
# │   │  │   │
# │   │  │   └─ 🔄 sync reconciles the environment with the project's
# │   │  │      resolved dependencies. It creates/updates the project's
# │   │  │      virtual environment, normally /app/.venv.
# │   │  │
# │   │  └─ 🧰 uv is the package manager installed from the separate
# │   │     Astral image above.
# │   │
# │   └─ 🏗️ RUN executes a command during IMAGE BUILD TIME.
# │      Its filesystem changes become part of a cached image layer.
# │
# └─ 🧠 WHY THIS TWO-PASS INSTALL WORKS:
#    The first sync installs external dependencies before source code
#    is copied. When application code changes, Docker can reuse this
#    expensive layer if the manifests and earlier build inputs match.
#    That saves rebuild time. ⚡


# ═══════════════════════════════════════════════════════════════════
# 🧑‍💻 STEP 4 — COPY THE SOURCE AND INSTALL THE PROJECT
# ═══════════════════════════════════════════════════════════════════

# Copy app code and install project
COPY . ./
# │    │ │  │
# │    │ │  └─ 📁 Destination: /app, because WORKDIR is /app.
# │    │ │
# │    │ └─ 📦 The entire Docker build context, subject to .dockerignore.
# │    │    It is NOT necessarily the entire computer or even every
# │    │    file in the Git repository.
# │    │
# │    └─ 🚚 COPY places the application source into the image.
# │
# └─ ⚠️ SECURITY + SIZE:
#    Add a .dockerignore file to exclude .git, local .venv directories,
#    caches, test artifacts, and secrets such as local .env files.
#    Otherwise they may enter the build context or image unnecessarily.
#    A .dockerignore exclusion is not a substitute for secret management.


RUN uv sync --locked --no-dev
# │   │  │   │       │        │
# │   │  │   │       │        └─ 🚫 Development dependency groups remain
# │   │  │   │       │           excluded, as in the earlier sync.
# │   │  │   │       │
# │   │  │   │       └─ 🔒 The same lockfile must still match the project.
# │   │  │   │
# │   │  │   └─ 🔄 Runs synchronization again, now with the project
# │   │  │      source present. uv can install the root application
# │   │  │      as well as its required dependencies.
# │   │  │
# │   │  └─ 🧰 The same uv tool is reused; no second installation
# │   │     of the package manager is needed.
# │   │
# │   └─ 🏗️ This is still BUILD TIME, not container startup.
# │
# └─ 🔗 CONNECTION TO THE PREVIOUS SYNC:
#    First sync: install dependencies without the root project.
#    Second sync: install the root project with the dependencies.
#    This separation allows dependency installation to remain cached
#    when only ordinary application source files change.


# ═══════════════════════════════════════════════════════════════════
# 🚀 STEP 5 — PRODUCTION STAGE: START WITH A FRESH, SMALL IMAGE
# ═══════════════════════════════════════════════════════════════════

# PRODUCTION STAGE
# └─ 🏷️ Human-readable comment, not a Docker instruction.

FROM python:3.14.4-slim-bookworm
# │    │
# │    └─ 🐍 Starts a NEW stage using the Python runtime image.
# │       This stage does not automatically inherit the builder's
# │       files, uv executable, or /app directory.
# │
# └─ 📦 MULTI-STAGE BUILD BENEFIT:
#    The final image starts clean. Only files explicitly copied from
#    the builder are brought across, plus files already in this base.
#    Build-only tools can therefore be omitted from the production image.
#    ⚠️ Python is still present because FastAPI needs it at runtime.


WORKDIR /app
# └─ 📁 Sets the working directory in the PRODUCTION stage.
#    This is a separate filesystem from the builder's /app.
#    The application will run from this directory.


# ═══════════════════════════════════════════════════════════════════
# 🛡️ STEP 6 — CREATE A NON-ROOT USER
# ═══════════════════════════════════════════════════════════════════

# Run as non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
# │   │       │      │       │  │     │     │       │
# │   │       │      │       │  │     │     │       └─ 👤 The owner
# │   │       │      │       │  │     │     │          becomes appuser.
# │   │       │      │       │  │     │     │
# │   │       │      │       │  │     │     └─ 📁 /app is the directory
# │   │       │      │       │  │     │        whose ownership is changed.
# │   │       │      │       │  │     │
# │   │       │      │       │  │     └─ 👥 appuser:appuser means
# │   │       │      │       │  │        user owner : group owner.
# │   │       │      │       │  │
# │   │       │      │       │  └─ 🔁 -R recursively changes ownership
# │   │       │      │       │     for /app and its existing contents.
# │   │       │      │       │
# │   │       │      │       └─ 🔧 chown changes file/directory ownership.
# │   │       │      │
# │   │       │      └─ 🏠 -m creates a home directory for appuser,
# │   │       │         typically /home/appuser on Debian.
# │   │       │
# │   │       └─ 👤 useradd creates a Linux account inside the image.
# │   │          It does not create a user on your host computer.
# │   │
# │   └─ 🏗️ RUN executes both commands during image construction.
# │
# └─ 🔗 && is a shell operator: run chown only if useradd succeeds.
#    This avoids changing ownership if account creation fails.
#    🛡️ SECURITY: a compromised app running as appuser has fewer
#    privileges than a process running as root.
#    ⚠️ chown -R only changes ownership of files already present.
#    The application and .venv are copied below, so the next instruction
#    must also assign their ownership correctly.


USER appuser
# │    └─ 👤 Sets the default Linux user for subsequent RUN instructions
# │       and the container's runtime process, unless overridden.
# │       Docker does NOT switch back to root automatically.
# │
# └─ 🛡️ WHY THIS MATTERS:
#    If FastAPI is compromised, an attacker does not immediately receive
#    root privileges inside the container. This reduces the blast radius.
#    It is defense in depth, not a complete security boundary.
#    ⚠️ The user must have read access to application files and write
#    access wherever the app genuinely needs to create files.


# ═══════════════════════════════════════════════════════════════════
# 📦 STEP 7 — COPY THE BUILT ENVIRONMENT INTO PRODUCTION
# ═══════════════════════════════════════════════════════════════════

# Copy app and dependencies from builder stage
COPY --from=builder --chown=appuser:appuser /app /app
# │    │             │                       │    │
# │    │             │                       │    └─ 📁 Destination:
# │    │             │                       │       /app in the production
# │    │             │                       │       stage.
# │    │             │                       │
# │    │             │                       └─ 📦 Source: /app in the
# │    │             │                          builder stage. This includes
# │    │             │                          the installed .venv and
# │    │             │                          application files.
# │    │             │
# │    │             └─ 👤 Assigns the copied files to appuser:appuser
# │    │                during the copy. This is essential because USER
# │    │                appuser was set before this instruction.
# │    │                Without the ownership option, copied files would
# │    │                normally be owned by root.
# │    │
# │    └─ 🔗 --from=builder identifies the named build stage created
# │       by AS builder near the beginning of this Dockerfile.
# │
# └─ 💡 IMPORTANT INTERDEPENDENCY:
#    The builder created /app/.venv using the Python base image.
#    The production image uses the same Python image tag, helping the
#    copied environment find a compatible interpreter.
#    ⚠️ Virtual environments are not universally portable across
#    different Python versions, filesystem layouts, or operating systems.
#    Using the same base image is an intentional compatibility measure.


# ═══════════════════════════════════════════════════════════════════
# 🔗 STEP 8 — CONFIGURE RUNTIME ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════════════

ENV PATH="/app/.venv/bin:$PATH"
# │   │    │
# │   │    └─ 📍 Prepends the virtual environment's bin directory
# │   │       to the existing PATH.
# │   │
# │   └─ ⚙️ PATH is the Linux environment variable that tells the shell
# │      where to search for executable commands.
# │
# └─ 🧠 WHY THE ORDER MATTERS:
#    The new PATH begins with /app/.venv/bin, followed by the old PATH.
#    Therefore, `fastapi` and other installed virtual-environment commands
#    are found before similarly named system-wide commands.
#    This connects directly to the earlier `uv sync` commands, which
#    normally create /app/.venv and install the project's CLI tools there.
#    ⚠️ If the project does not install the FastAPI CLI, this PATH change
#    cannot magically create the `fastapi` command.


ENV PYTHONUNBUFFERED=1
# │   │                 └─ 🔄 Prevents Python from buffering stdout
# │   │                    and stderr in the usual way.
# │   │                    Log output can appear promptly in `docker logs`
# │   │                    rather than waiting for a buffer to flush.
# │   │
# └─ 📋 This is an observability improvement: prompt logs help you diagnose
#    startup errors and production incidents.
#    It does NOT enable logging by itself.


ENV PORT=8080
# │   │      └─ 🔢 Provides the default port value for the application.
# │   │         The CMD below reads "$PORT" when the container starts.
# │   │
# └─ 🔗 This is a default, not a hardcoded requirement. A deployment
#    platform can override the PORT environment variable at runtime.
#    The application must still bind to the same port that the platform
#    expects it to use. 📡


# ═══════════════════════════════════════════════════════════════════
# 🌐 STEP 9 — START FASTAPI AND HANDLE SHUTDOWN CORRECTLY
# ═══════════════════════════════════════════════════════════════════

# exec replaces shell so fastapi receives SIGTERM for clean shutdown
CMD ["/bin/sh", "-c", "exec fastapi run --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips '*'"]
# │    │           │    │       │     │      │          │
# │    │           │    │       │     │      │          └─ 🌍 --forwarded-allow-ips '*'
# │    │           │    │       │     │      │             trusts forwarded headers
# │    │           │    │       │     │      │             from ALL proxy IP addresses.
# │    │           │    │       │     │      │             This can be dangerous if
# │    │           │    │       │     │      │             clients can bypass the
# │    │           │    │       │     │      │             trusted reverse proxy.
# │    │           │    │       │     │      │             Use a restricted proxy IP
# │    │           │    │       │     │      │             or network boundary when
# │    │           │    │       │     │      │             your deployment allows it.
# │    │           │    │       │     │      │             🛡️ Trust only known proxies.
# │    │           │    │       │     │      │
# │    │           │    │       │     │      └─ 🔀 --proxy-headers enables handling
# │    │           │    │       │     │         of forwarded headers such as
# │    │           │    │       │     │         X-Forwarded-For and X-Forwarded-Proto.
# │    │           │    │       │     │         These can tell FastAPI/Uvicorn which
# │    │           │    │       │     │         client IP and original URL scheme
# │    │           │    │       │     │         the proxy observed.
# │    │           │    │       │     │         The trusted-IP setting controls which
# │    │           │    │       │     │         senders are allowed to influence them.
# │    │           │    │       │     │
# │    │           │    │       │     └─ 🔢 --port "$PORT" sets the listening port
# │    │           │    │       │        from the environment variable.
# │    │           │    │       │        The double quotes keep the expansion as
# │    │           │    │       │        one shell argument. If PORT=8080, the
# │    │           │    │       │        resulting argument is 8080.
# │    │           │    │       │
# │    │           │    │       └─ 🌐 --host 0.0.0.0 tells the server to listen
# │    │           │    │          on all container network interfaces.
# │    │           │    │          Binding to 127.0.0.1 instead would generally
# │    │           │    │          prevent access through the container's network
# │    │           │    │          interface from outside the container.
# │    │           │    │
# │    │           │    └─ 🚀 fastapi run invokes the FastAPI CLI to start
# │    │           │       the application. The CLI discovers/imports the app
# │    │           │       using its configured discovery rules.
# │    │           │       ⚠️ This assumes the project has the FastAPI CLI
# │    │           │       installed and the app can be discovered from /app.
# │    │           │
# │    │           └─ 🔄 -c tells /bin/sh to execute the supplied command string.
# │    │              The shell expands "$PORT" at container startup.
# │    │
# │    └─ 🐚 /bin/sh is the shell executable inside the container.
# │
# └─ 🏁 CMD specifies the default container startup command in EXEC form.
#    Docker starts /bin/sh with the provided arguments.
#    Then `exec` replaces that shell process with the FastAPI CLI process.
#    This lets the application receive container stop signals directly,
#    supporting graceful shutdown rather than leaving the shell as an
#    unnecessary intermediary. 🛑
#
# ⚠️ PRODUCTION SECURITY NOTE:
#    `--forwarded-allow-ips '*'` is the riskiest setting here.
#    It is appropriate only when the app is protected so untrusted clients
#    cannot send spoofed forwarded headers directly to it.
#    If clients can reach this port directly, they may falsify client IP
#    or scheme information. Prefer an explicit trusted-proxy configuration
#    when the hosting platform's network setup makes that possible.