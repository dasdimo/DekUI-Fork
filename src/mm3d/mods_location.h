// SPDX-License-Identifier: GPL-2.0-or-later
// Locates the LayeredFS directory of the game actually set up in a user tree.
// The in-game settings installers (sub-menu header, HUD, banners, notebook)
// run without a Core::System, so they resolve the title from what Setup
// installed instead of hard-coding either title id. Qt-only header so the
// Android overlay target can use it too.
#pragma once
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QList>
#include <QString>

#include "mm3d/title_ids.h"

namespace MM3D::ModsLocation {

// Lower-case 16-digit title id whose mods/ directory is installed under
// load_dir, or an empty string when no supported game is installed. When
// several supported titles are installed, the title recorded by Setup in
// ../setup/ready.json wins, then the one containing required_file, then the
// first in MajoraMask3DUsaTitle, MajoraMask3DEurTitle order.
inline QString InstalledTitleId(const QString& load_dir,
                                const QString& required_file = QString())
{
    QList<QString> installed;
    for (const std::uint64_t id : {MM3D::MajoraMask3DUsaTitle, MM3D::MajoraMask3DEurTitle}) {
        const QString hex = QStringLiteral("%1").arg(id, 16, 16, QLatin1Char('0'));
        if (QFileInfo::exists(QDir(load_dir).absoluteFilePath(QStringLiteral("mods/") + hex)))
            installed.append(hex);
    }
    if (installed.isEmpty())
        return {};
    if (installed.size() == 1)
        return installed.first();
    const QFile ready(QDir(load_dir).absoluteFilePath(QStringLiteral("../setup/ready.json")));
    if (ready.open(QIODevice::ReadOnly)) {
        const QString title = QJsonDocument::fromJson(ready.readAll()).object()
                                  .value(QStringLiteral("title_id")).toString().toLower();
        if (installed.contains(title))
            return title;
    }
    for (const QString& hex : installed)
        if (!required_file.isEmpty() && QFileInfo::exists(QDir(load_dir).absoluteFilePath(
                                           QStringLiteral("mods/") + hex + QLatin1Char('/') + required_file)))
            return hex;
    return installed.first();
}

} // namespace MM3D::ModsLocation
