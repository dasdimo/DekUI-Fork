// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>
#include <QStandardPaths>
#include "mm3d/desktop_storage.h"
#include "mm3d/mods_location.h"
#include "mm3d/title_ids.h"

namespace MM3D::GameFolder {
// Verified Rev 1 main partitions; see resources/mm3d/supported-rom.json.
inline constexpr auto UsaHash = "9c756279e3ec00bb9009f92ca2e7b9ec8b1fcdfcd9de057658b209caa24323da";
inline constexpr auto EurHash = "a26108ef34b49df421cca20eda1b4f38f596ebef9ac6b9c70a64245be055a722";
inline constexpr quint64 UsaSize = 654643200, EurSize = 668647424;
inline QString LegacyRoot() {
    // AppImage mounts its executable read-only; use the folder holding the image.
    const auto appimage = qEnvironmentVariable("APPIMAGE");
#ifdef Q_OS_MACOS
    // The executable is inside Majora ReMasked.app/Contents/MacOS; portable data and
    // the user's game belong beside the app, outside its signed contents.
    QDir bundle(QCoreApplication::applicationDirPath());
    if (bundle.dirName() == QStringLiteral("MacOS") && bundle.cdUp() &&
        bundle.dirName() == QStringLiteral("Contents") && bundle.cdUp() &&
        bundle.dirName().endsWith(QStringLiteral(".app")) && bundle.cdUp())
        return bundle.absolutePath();
#endif
    return appimage.isEmpty() ? QCoreApplication::applicationDirPath()
                              : QFileInfo(appimage).absolutePath();
}
inline QString PackageRoot() {
#ifdef Q_OS_MACOS
    const auto embedded=QDir(QCoreApplication::applicationDirPath()).absoluteFilePath(QStringLiteral("../Resources"));
    if (QFileInfo::exists(embedded+QStringLiteral("/tools/mm3d/graphical_setup.py"))) return embedded;
#endif
    return LegacyRoot();
}
inline QString Root() {
#ifdef Q_OS_MACOS
    // Keep the established data directory across display-name changes.
    return QStandardPaths::writableLocation(QStandardPaths::GenericDataLocation)+QStringLiteral("/DekUI Fork");
#else
    return LegacyRoot();
#endif
}
inline QString InitializeStorage() {
#ifdef Q_OS_MACOS
    return DesktopStorage::Migrate(LegacyRoot(),Root());
#else
    return {};
#endif
}
inline QString FindRom(const QString& root) {
    QFile selection(root+QStringLiteral("/desktop-settings.json"));
    if(selection.open(QIODevice::ReadOnly)) {
        const auto chosen=QJsonDocument::fromJson(selection.readAll()).object().value(QStringLiteral("mm_rom")).toString();
        if(!chosen.isEmpty())return QFileInfo(chosen).isFile()?chosen:QString{};
    }
    QStringList candidates;
    for (const auto& file : QDir(root).entryInfoList(QDir::Files, QDir::Name)) {
        const auto suffix=file.suffix().toLower();
        if(suffix==QStringLiteral("cci") || suffix==QStringLiteral("3ds"))
            candidates.push_back(file.absoluteFilePath());
    }
    if(candidates.size()==1)return candidates.front();
    if(!candidates.empty())return {}; // Never silently choose between games.
    // Preserve existing portable installations without moving their game/saves.
    const auto legacy=root+QStringLiteral("/game/mm3d.cci");
    return QFileInfo(legacy).isFile()?legacy:QString{};
}
inline QString Rom() {
    const auto chosen=FindRom(Root());
#ifdef Q_OS_MACOS
    if(chosen.isEmpty()&&!QFileInfo::exists(Root()+QStringLiteral("/desktop-settings.json")))
        return FindRom(LegacyRoot());
#endif
    return chosen;
}
inline QString MissingGameMessage() {
    return QStringLiteral("Select your decrypted MM3D USA or Europe Rev 1 game-card dump (.cci or .3ds) from the startup screen.");
}
inline QString User() { return Root() + QStringLiteral("/user/"); }
inline QString ValidateSetup(const QString& user) {
    QFile ready(QDir(user).filePath(QStringLiteral("setup/ready.json")));
    if(!ready.open(QIODevice::ReadOnly)) return QStringLiteral("Game setup is incomplete. Preserve your user folder and saves, then try a fresh application folder.");
    const auto setup=QJsonDocument::fromJson(ready.readAll()).object();
    const auto sha=setup[QStringLiteral("rom_sha256")].toString();
    if(setup[QStringLiteral("version")].toInt()!=1 || (sha!=QString::fromLatin1(UsaHash) && sha!=QString::fromLatin1(EurHash)))
        return QStringLiteral("Game setup is incompatible. Keep your saves and prepare a new application folder.");
    if(setup[QStringLiteral("resource_version")].toInt()!=2 ||
       setup[QStringLiteral("layout_version")].toInt()!=2 ||
       QFileInfo::exists(QDir(user).filePath(QStringLiteral("setup/resource-upgrade-pending"))))
        return QStringLiteral("Game resource upgrade is incomplete. Close Majora ReMasked and launch again to retry. Preserve your user folder and its upgrade backups.");
    return {};
}
inline QString Validate() {
    QFile file(Rom());
    if (!file.open(QIODevice::ReadOnly))
        return MissingGameMessage();
    const auto header = file.read(512);
    if (header.size()!=512 || header.mid(0x100,4)!="NCSD") return QStringLiteral("Unsupported game container.");
    const auto word = [&](int at) { return qFromLittleEndian<quint32>(header.constData()+at); };
    const quint64 base=quint64(word(0x120))*512, size=quint64(word(0x124))*512;
    if(base<512 || (size!=UsaSize && size!=EurSize) || base+size>quint64(file.size()) || !file.seek(base))
        return QStringLiteral("Unsupported or incomplete game dump.");
    QCryptographicHash hash(QCryptographicHash::Sha256);
    for (quint64 remaining=size; remaining;) {
        const auto bytes=file.read(qint64(qMin<quint64>(remaining,1024*1024)));
        if(bytes.isEmpty()) return QStringLiteral("Could not read the game.");
        hash.addData(bytes); remaining-=bytes.size();
    }
    const auto digest=hash.result().toHex();
    if(digest!=QByteArray(UsaHash) && digest!=QByteArray(EurHash)) return QStringLiteral("Unsupported game revision/content. The supported decrypted USA or Europe Rev 1 dump is required.");
    return ValidateSetup(User());
}
inline QString SelectedTitleId(const QString& root) {
    // Lower-case title id of the game Setup prepared: the record in
    // user/setup/ready.json wins, then the game card beside the app, then a
    // scan of installed mods/ directories. Never hard-codes either title.
    const auto user=QDir(root).absoluteFilePath(QStringLiteral("user"));
    QFile ready(QDir(user).filePath(QStringLiteral("setup/ready.json")));
    if(ready.open(QIODevice::ReadOnly)) {
        const QString title=QJsonDocument::fromJson(ready.readAll()).object()
            .value(QStringLiteral("title_id")).toString().toLower();
        bool ok=false;const quint64 id=title.toULongLong(&ok,16);
        if(ok&&IsMajoraMask3DTitle(id)) return title;
    }
    QFile file(FindRom(root));
    if(file.open(QIODevice::ReadOnly)) {
        const auto header=file.read(512);
        if(header.size()==512&&header.mid(0x100,4)=="NCSD") {
            const quint64 base=quint64(qFromLittleEndian<quint32>(header.constData()+0x120))*512;
            if(base>=512&&file.seek(base)) {
                const auto ncch=file.read(512);
                if(ncch.size()==512&&ncch.mid(0x100,4)=="NCCH") {
                    const quint64 id=qFromLittleEndian<quint64>(ncch.constData()+0x118);
                    if(IsMajoraMask3DTitle(id)) return QStringLiteral("%1").arg(id,16,16,QLatin1Char('0'));
                }
            }
        }
    }
    return ModsLocation::InstalledTitleId(QDir(user).absoluteFilePath(QStringLiteral("load")));
}
}
