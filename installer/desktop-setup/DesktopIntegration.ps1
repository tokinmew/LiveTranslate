# Loaded by the graphical installer's Setup.ps1 and by its installed uninstaller.
function Update-DesktopRegistration($hive,[string]$keyPath,[string]$appDir,[version]$version,
                                    [bool]$remove,[bool]$checkOnly) {
    $owner = 'LiveTranslate per-user desktop setup|' + $appDir
    $launcher = Under $appDir '.lt-setup/LiveTranslate.Launcher.exe'
    $key = $hive.OpenSubKey($keyPath, (!$checkOnly -and !$remove))
    try {
        if ($key -and $key.GetValue('LiveTranslateSetupOwner', '') -ine $owner) {
            if ($remove) { return }
            throw 'Windows already has an unrelated Installed apps entry named LiveTranslate.'
        }
        if ($checkOnly) { return }
        if ($remove) {
            if (!$key -or $key.SubKeyCount -ne 0) { return }
            $key.Dispose()
            $key = $null
            $hive.DeleteSubKey($keyPath, $false)
            return
        }
        if (!$key) { $key = $hive.CreateSubKey($keyPath) }
        $key.SetValue('LiveTranslateSetupOwner', $owner)
        $key.SetValue('DisplayName', 'LiveTranslate')
        $key.SetValue('DisplayVersion', $version.ToString(3))
        $key.SetValue('Publisher', 'LiveTranslate project')
        $key.SetValue('InstallLocation', $appDir)
        $key.SetValue('DisplayIcon', ('"' + (Under $appDir 'LiveTranslate.exe') + '",0'))
        $key.SetValue('UninstallString', ('"' + $launcher + '" --uninstall'))
        $key.SetValue('NoModify', 1, [Microsoft.Win32.RegistryValueKind]::DWord)
        $key.SetValue('NoRepair', 1, [Microsoft.Win32.RegistryValueKind]::DWord)
    } finally { if ($key) { $key.Dispose() } }
}

function Set-DesktopLinks([string]$menu,[string]$appDir,[bool]$remove,[bool]$checkOnly=$false) {
    $appDir = [IO.Path]::GetFullPath($appDir)
    $menu = [IO.Path]::GetFullPath($menu)
    Plain-Path $menu
    $dashboard = Under $appDir 'LiveTranslate.exe'
    $launcher = Under $appDir '.lt-setup/LiveTranslate.Launcher.exe'
    if (!$remove -and [IO.File]::Exists($dashboard)) {
        $info = [Diagnostics.FileVersionInfo]::GetVersionInfo($dashboard)
        $actual = [version]::new($info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart)
        # An older installer cannot know which launchers belong to a newer release.
        if ($actual -gt $releaseVersion) { return }
    }

    $profileApp = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\LiveTranslate\app'
    $profileMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'LiveTranslate'
    $register = $appDir -ieq $profileApp -and $menu -ieq $profileMenu
    $registryPath = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\LiveTranslate'
    if ($register -and !$remove) {
        Update-DesktopRegistration ([Microsoft.Win32.Registry]::CurrentUser) $registryPath $appDir $releaseVersion $false $true
    }
    if (![IO.Directory]::Exists($menu) -and !$checkOnly -and !$remove) {
        [void][IO.Directory]::CreateDirectory($menu)
    }
    if ([IO.Directory]::Exists($menu)) {
        $shell = New-Object -ComObject WScript.Shell
        try {
            $ps = Join-Path ([Environment]::SystemDirectory) 'WindowsPowerShell\v1.0\powershell.exe'
            foreach ($title in @('LiveTranslate','Uninstall LiveTranslate')) {
                $file = Under $menu ($title + '.lnk')
                Plain-Path $file
                $exists = [IO.File]::Exists($file)
                if (!$exists -and ($remove -or $checkOnly)) { continue }
                $uninstall = $title -eq 'Uninstall LiveTranslate'
                $argsText = if ($uninstall) { '--uninstall' } else { '' }
                $target = if ($uninstall) { $launcher } else { $dashboard }
                $oldTarget = if ($uninstall) { $ps } else { Under $appDir 'Start.cmd' }
                $oldArgs = if ($uninstall) {
                    '-NoLogo -NoProfile -STA -ExecutionPolicy Bypass -File "' + (Under $appDir '.lt-setup/Setup.ps1') + '" -Uninstall'
                } else { '' }
                $shortcut = $shell.CreateShortcut($file)
                try {
                    $native = $shortcut.TargetPath -ieq $launcher -and $shortcut.Arguments -ieq $argsText
                    $legacy = $shortcut.TargetPath -ieq $oldTarget -and $shortcut.Arguments -ieq $oldArgs
                    $current = $shortcut.TargetPath -ieq $target -and $shortcut.Arguments -ieq $argsText
                    if ($exists -and !$current -and !$native -and !$legacy) {
                        if ($remove) { continue }
                        throw "A different shortcut exists at $file"
                    }
                    if ($checkOnly) { continue }
                    if ($remove) { [IO.File]::Delete($file); continue }
                    $shortcut.TargetPath = $target
                    $shortcut.Arguments = $argsText
                    $shortcut.WorkingDirectory = if ($uninstall) { [IO.Path]::GetDirectoryName($appDir) } else { $appDir }
                    $shortcut.IconLocation = $dashboard + ',0'
                    $shortcut.Save()
                } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shortcut) }
            }
        } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell) }
        if ($remove -and [IO.Directory]::GetFileSystemEntries($menu).Length -eq 0) { [IO.Directory]::Delete($menu) }
    }
    if ($register -and !$checkOnly) {
        Update-DesktopRegistration ([Microsoft.Win32.Registry]::CurrentUser) $registryPath $appDir $releaseVersion $remove $false
    }
}
