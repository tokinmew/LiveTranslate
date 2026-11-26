using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Web.Script.Serialization;

namespace LiveTranslate
{
    internal sealed class VrConnectionLayout
    {
        public decimal width = .9M, distance = 1.6M, height = -.4M;
        public int opacity = 95;
    }
    internal sealed class VrConnectionProfiles
    {
        internal static readonly string[] Codes = { "steamvr", "virtualdesktop", "steamlink", "questlink", "openxr" };
        internal static readonly string[] Names = { "SteamVR", "Virtual Desktop + SteamVR", "Steam Link + SteamVR", "Quest Link + SteamVR", "OpenXR / VDXR (overlay unavailable)" };
        internal string Selected = "steamvr";
        readonly Dictionary<string, VrConnectionLayout> layouts = new Dictionary<string, VrConnectionLayout>();
        internal VrConnectionLayout Get(string code)
        {
            if (Array.IndexOf(Codes, code) < 0) code = "steamvr";
            VrConnectionLayout layout;
            if (!layouts.TryGetValue(code, out layout)) layouts[code] = layout = new VrConnectionLayout();
            return layout;
        }
        static decimal Number(Dictionary<string, object> values, string name, decimal fallback, decimal low, decimal high)
        {
            object value;
            try { return values.TryGetValue(name, out value) ? Math.Max(low, Math.Min(high, Convert.ToDecimal(value, CultureInfo.InvariantCulture))) : fallback; }
            catch (Exception) { return fallback; }
        }
        static VrConnectionLayout Decode(Dictionary<string, object> values)
        {
            return new VrConnectionLayout { width = Number(values, "width", .9M, .35M, 1.4M),
                distance = Number(values, "distance", 1.6M, .7M, 3M), height = Number(values, "height", -.4M, -.9M, .2M),
                opacity = (int)Number(values, "opacity", 95, 0, 100) };
        }
        internal static VrConnectionProfiles Read(string path)
        {
            var result = new VrConnectionProfiles();
            try
            {
                if (!File.Exists(path) || new FileInfo(path).Length > 32768) return result;
                var values = new JavaScriptSerializer().DeserializeObject(File.ReadAllText(path)) as Dictionary<string, object>;
                if (values == null) return result;
                object saved;
                if (values.TryGetValue("connection", out saved) && saved is string && Array.IndexOf(Codes, (string)saved) >= 0) result.Selected = (string)saved;
                if (values.TryGetValue("profiles", out saved))
                {
                    var profiles = saved as Dictionary<string, object>;
                    if (profiles != null) foreach (string code in Codes)
                    {
                        object raw;
                        if (profiles.TryGetValue(code, out raw) && raw is Dictionary<string, object>) result.layouts[code] = Decode((Dictionary<string, object>)raw);
                    }
                }
                else result.layouts["steamvr"] = Decode(values); // Preserve the 0.8.0 placement file.
            }
            catch (Exception) { }
            return result;
        }
        internal void Write(string path)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var values = new Dictionary<string, object>();
            foreach (string code in Codes) values[code] = Get(code);
            string temporary = path + ".tmp";
            try
            {
                File.WriteAllText(temporary, new JavaScriptSerializer().Serialize(new Dictionary<string, object> {
                    { "connection", Selected }, { "profiles", values } }));
                if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
