# Ai-SSS Credentials & Environment Configuration

This document contains the default credentials and environment configuration for the local development environment as defined in your `.env.example`.

> [!WARNING]
> Do not use these default passwords in a production environment. Always change them and generate secure secret keys.

## PostgreSQL Database

- **Database Name:** `surveillance_db`
- **Username:** `surveillance`
- **Password:** `CHANGE_THIS_TO_A_STRONG_PASSWORD`
- **Port:** `5432`
- **Host:** `localhost`
- **Connection URL:** `postgresql://surveillance:CHANGE_THIS_TO_A_STRONG_PASSWORD@localhost:5432/surveillance_db`

## Backend API Configuration

- **Host URL:** `http://localhost:8000`
- **Swagger Documentation:** `http://localhost:8000/docs`
- **JWT Algorithm:** `HS256`
- **Access Token Expiration:** `30 minutes`
- **Default Secret Key:** `CHANGE_THIS_SECRET_KEY_IN_PRODUCTION_64_CHARS_MIN`

> [!TIP]
> *To generate a new secure secret key for production, run:*
> ```bash
> python3 -c "import secrets; print(secrets.token_urlsafe(64))"
> ```

## Encryption Configuration
Video evidence is encrypted before saving using AES-256. 

> [!TIP]
> *To generate a new encryption key for production, run:*
> ```bash
> python3 -c "import secrets; print(secrets.token_urlsafe(32))"
> ```
