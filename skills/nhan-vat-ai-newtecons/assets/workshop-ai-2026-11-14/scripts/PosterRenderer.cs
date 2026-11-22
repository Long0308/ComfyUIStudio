using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;
using System.IO;

public sealed class PosterFitRecord
{
    public string Poster { get; set; }
    public string Text { get; set; }
    public string Font { get; set; }
    public string Style { get; set; }
    public float FontSize { get; set; }
    public float X { get; set; }
    public float Y { get; set; }
    public float Width { get; set; }
    public float Height { get; set; }
    public float MeasuredWidth { get; set; }
    public bool Fits { get; set; }
}

public static partial class PosterRenderer
{
    public static readonly List<PosterFitRecord> Audit = new List<PosterFitRecord>();
    static readonly Color Navy = Color.FromArgb(10,37,64);
    static readonly Color Blue = Color.FromArgb(11,79,217);
    static readonly Color Pale = Color.FromArgb(226,240,255);
    static readonly Color Rule = Color.FromArgb(173,198,226);
    static readonly Color Meta = Color.FromArgb(34,70,116);
    static readonly string[] Times = {"08:55 – 09:10","09:10 – 09:25","09:25 – 09:40","09:40 – 09:55","09:55 – 10:15"};
    static readonly string[] Titles = {
        "1. Claude – Trợ lý văn phòng công trường",
        "2. Claude – Trợ thủ đắc lực cho QS",
        "3. Dashboard – Tiến độ, T&C và hồ sơ trong tầm tay",
        "4. AI – Kiến tạo công cụ quản lý công trường",
        "5. AI Agent – Triển khai bản vẽ, tính tổn thất ống gió"
    };
    static readonly string[] Presenters = {
        "Trình bày: Trần Dương Hồng Quân - Dự án: Sân bay Long Thành",
        "Trình bày: Nguyễn Văn Hải - Dự án: The One Sài Gòn",
        "Trình bày: Nguyễn Đình Thiệu - Dự án: Sân bay Long Thành",
        "Trình bày: Nguyễn Thanh Hoàng - Dự án: Bason",
        "Trình bày: Phạm Phi Long & Ngô Ngọc Sơn - Văn phòng: Khối Kỹ Thuật"
    };
    static readonly string[] PartTwo = {
        "(1)  Các cấp độ ứng dụng AI",
        "(2)  Phân biệt AI cá nhân và AI doanh nghiệp",
        "(3)  Hướng dẫn sử dụng AI có trách nhiệm",
        "(4)  Giới thiệu câu lạc bộ AI HST"
    };

    static Font NewFont(float size, FontStyle style, string family = "Roboto Condensed")
    {
        return new Font(family, size, style, GraphicsUnit.Pixel);
    }

    static StringFormat Format()
    {
        var f = (StringFormat)StringFormat.GenericTypographic.Clone();
        f.FormatFlags &= ~StringFormatFlags.LineLimit;
        f.FormatFlags |= StringFormatFlags.NoWrap | StringFormatFlags.MeasureTrailingSpaces | StringFormatFlags.NoClip;
        f.Trimming = StringTrimming.None;
        return f;
    }

    static float Measure(Graphics g, string text, float size, FontStyle style, string family = "Roboto Condensed")
    {
        using (var font = NewFont(size, style, family))
        using (var format = Format())
            return g.MeasureString(text, font, new SizeF(10000,1000), format).Width;
    }

    static float Fit(Graphics g, IEnumerable<string> text, float maxSize, float minSize, float width, FontStyle style, string family = "Roboto Condensed")
    {
        float size = maxSize;
        while (size >= minSize)
        {
            bool fits = true;
            foreach (var s in text) if (Measure(g,s,size,style,family) > width - 4) { fits = false; break; }
            if (fits) return size;
            size -= 0.5f;
        }
        throw new InvalidOperationException("Cannot fit text: " + string.Join(" / ", text));
    }

    static void Text(Graphics g, string poster, string text, float x, float y, float width, float height, float size, FontStyle style, Color color, string family = "Roboto Condensed", bool center = false)
    {
        float measured = Measure(g,text,size,style,family);
        bool fits = measured <= width + 0.1f;
        Audit.Add(new PosterFitRecord { Poster=poster,Text=text,Font=family,Style=style.ToString(),FontSize=size,X=x,Y=y,Width=width,Height=height,MeasuredWidth=measured,Fits=fits });
        if (!fits) throw new InvalidOperationException("Text overflows: " + text + " measured="+measured+" width="+width);
        using (var font = NewFont(size,style,family))
        using (var brush = new SolidBrush(color))
        using (var format = Format())
        {
            format.Alignment = center ? StringAlignment.Center : StringAlignment.Near;
            float drawX = center ? x + (width-measured)/2 : x;
            format.Alignment = StringAlignment.Near;
            g.DrawString(text,font,brush,new PointF(drawX,y),format);
        }
    }

    static void Rect(Graphics g, Color color, float x, float y, float w, float h)
    {
        using (var brush = new SolidBrush(color)) g.FillRectangle(brush,x,y,w,h);
    }
    static void Line(Graphics g, Color color, float width, float x1,float y1,float x2,float y2)
    {
        using (var pen = new Pen(color,width)) g.DrawLine(pen,x1,y1,x2,y2);
    }
    static void Polygon(Graphics g, Color color, params PointF[] points)
    {
        using (var brush = new SolidBrush(color)) g.FillPolygon(brush,points);
    }

    static void Section(Graphics g,string poster,string label,string sub,float x,float y,float width,float height,float labelWidth,float labelSize,float subSize)
    {
        Rect(g,Pale,x,y,width,height);
        Polygon(g,Blue,new PointF(x,y),new PointF(x+labelWidth-38,y),new PointF(x+labelWidth+30,y+height),new PointF(x,y+height));
        Polygon(g,Color.FromArgb(188,220,253),new PointF(x+labelWidth-20,y),new PointF(x+labelWidth+8,y),new PointF(x+labelWidth+76,y+height),new PointF(x+labelWidth+48,y+height));
        Text(g,poster,label,x+40,y+9,labelWidth-50,height-10,labelSize,FontStyle.Bold,Color.White);
        if (!string.IsNullOrEmpty(sub))
        {
            float subX=x+labelWidth+100;
            float size=Fit(g,new[]{sub},subSize,30,width-(subX-x)-22,FontStyle.Bold);
            Text(g,poster,sub,subX,y+14,width-(subX-x)-22,height-10,size,FontStyle.Bold,Navy);
        }
    }

    static void Time(Graphics g,string poster,string time,float x,float y,float w,float h,float size)
    {
        Polygon(g,Pale,new PointF(x+23,y),new PointF(x+w-23,y),new PointF(x+w,y+h/2),new PointF(x+w-23,y+h),new PointF(x+23,y+h),new PointF(x,y+h/2));
        Text(g,poster,time,x+18,y+6,w-36,h-5,size,FontStyle.Bold,Navy,"Roboto Condensed",true);
    }

    static void Node(Graphics g,float x,float y)
    {
        using (var white=new SolidBrush(Color.White)) g.FillEllipse(white,x-17,y-17,34,34);
        using (var pen=new Pen(Blue,6)) g.DrawEllipse(pen,x-17,y-17,34,34);
    }

    static void Hero(Graphics g,Image hero,RectangleF destination)
    {
        float scale=Math.Max(destination.Width/hero.Width,destination.Height/hero.Height);
        float sw=destination.Width/scale,sh=destination.Height/scale;
        var source=new RectangleF((hero.Width-sw)/2,(hero.Height-sh)/2,sw,sh);
        using (var attrs=new ImageAttributes())
        {
            attrs.SetWrapMode(WrapMode.TileFlipXY);
            g.DrawImage(hero,Rectangle.Round(destination),source.X,source.Y,source.Width,source.Height,GraphicsUnit.Pixel,attrs);
        }
    }

    static void Logo(Graphics g,Image logo,float x,float y,float width)
    {
        g.DrawImage(logo,new RectangleF(x,y,width,width*logo.Height/logo.Width));
    }

    static void Qr(Graphics g,Image qr,float x,float y,float size)
    {
        Rect(g,Color.White,x-15,y-15,size+30,size+30);
        var oldMode=g.InterpolationMode;
        var oldOffset=g.PixelOffsetMode;
        g.InterpolationMode=InterpolationMode.NearestNeighbor;
        g.PixelOffsetMode=PixelOffsetMode.Half;
        g.DrawImage(qr,new RectangleF(x,y,size,size),new RectangleF(100,0,800,800),GraphicsUnit.Pixel);
        g.InterpolationMode=oldMode;
        g.PixelOffsetMode=oldOffset;
    }

    static void Configure(Graphics g)
    {
        g.Clear(Color.White);
        g.SmoothingMode=SmoothingMode.AntiAlias;
        g.CompositingQuality=CompositingQuality.HighQuality;
        g.InterpolationMode=InterpolationMode.HighQualityBicubic;
        g.PixelOffsetMode=PixelOffsetMode.HighQuality;
        g.TextRenderingHint=TextRenderingHint.AntiAliasGridFit;
        g.PageUnit=GraphicsUnit.Pixel;
    }

    static void Portrait(Image hero,Image logo,Image qr,string output)
    {
        const string P="portrait-9x16";
        using(var bitmap=new Bitmap(2160,3840,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300); Configure(g);
            Hero(g,hero,new RectangleF(0,0,2160,804));
            Polygon(g,Blue,new PointF(0,744),new PointF(116,804),new PointF(0,922));
            Polygon(g,Blue,new PointF(2160,744),new PointF(2044,804),new PointF(2160,922));
            Logo(g,logo,330,840,635);
            Line(g,Blue,3,1045,850,1045,979);
            Text(g,P,"KHỐI CƠ ĐIỆN",1130,870,800,110,77,FontStyle.Bold,Navy);
            Text(g,P,"TIMELINE WORKSHOP AI",88,1020,1984,154,128,FontStyle.Bold,Navy,"Roboto Condensed",true);
            Text(g,P,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",90,1186,1980,76,55,FontStyle.Bold,Navy,"Roboto Condensed",true);
            Line(g,Blue,4,72,1290,2088,1290);
            Section(g,P,"MỞ ĐẦU","",72,1320,2016,94,550,72,62);
            Line(g,Blue,5,145,1425,145,1694);
            string[] openingTimes={"08:30 – 08:40","08:40 – 08:55"};
            string[] openingTitles={"VÕ THANH CANG","Minigame: Giải mã công trường AI"};
            string[] openingMeta={"Giám đốc Khối Cơ Điện chia sẻ","Quà hấp dẫn"};
            for(int i=0;i<2;i++)
            {
                float y=1440+i*140;
                Node(g,145,y+36); Time(g,P,openingTimes[i],200,y,365,84,48);
                Line(g,Rule,2,612,y,612,y+104);
                Text(g,P,openingTitles[i],650,y-8,1420,82,61,FontStyle.Bold,Navy);
                Text(g,P,openingMeta[i],650,y+67,1420,70,48,FontStyle.Regular,Meta);
                if(i==0) Line(g,Rule,2,650,y+129,2088,y+129);
            }
            Section(g,P,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",72,1730,2016,94,490,72,55);
            float titleSize=Fit(g,Titles,58,42,1458,FontStyle.Bold);
            float metaSize=Fit(g,Presenters,44,34,1437,FontStyle.Italic);
            Line(g,Blue,5,145,1826,145,2638);
            for(int i=0;i<5;i++)
            {
                float y=1850+i*160;
                Node(g,145,y+39);Time(g,P,Times[i],200,y,365,84,48);
                Line(g,Rule,2,612,y-2,612,y+117);
                Text(g,P,Titles[i],630,y-7,1458,87,titleSize,FontStyle.Bold,Navy);
                Text(g,P,Presenters[i],651,y+72,1437,72,metaSize,FontStyle.Italic,Meta);
                if(i<4) Line(g,Rule,2,630,y+143,2088,y+143);
            }
            Section(g,P,"PHẦN 2","10:15 – 10:50",72,2705,2016,94,490,72,61);
            Text(g,P,"ỨNG DỤNG AI CÓ TRÁCH NHIỆM",145,2820,1943,84,67,FontStyle.Bold,Navy);
            Text(g,P,"Trình bày: Trương Quang Vinh - Văn phòng: P.CNTT",145,2900,1943,72,48,FontStyle.Italic,Meta);
            for(int i=0;i<4;i++) Text(g,P,PartTwo[i],155,2987+i*65,1933,70,49,FontStyle.Regular,Navy);
            Section(g,P,"PHẦN 3","10:50 – 11:00",72,3287,2016,94,490,72,61);
            Text(g,P,"TỔNG KẾT",145,3402,1943,90,76,FontStyle.Bold,Navy);
            Qr(g,qr,914,3507,332);
            Polygon(g,Color.FromArgb(228,242,255),new PointF(0,3800),new PointF(390,3800),new PointF(345,3840),new PointF(0,3840));
            Polygon(g,Color.FromArgb(228,242,255),new PointF(2160,3530),new PointF(2160,3840),new PointF(1840,3840));
            Polygon(g,Blue,new PointF(2160,3650),new PointF(2160,3840),new PointF(1960,3840));
            bitmap.Save(Path.Combine(output,"Newtecons-Workshop-AI-NEW-9x16-2160x3840.png"),ImageFormat.Png);
        }
    }

    static void Landscape(Image hero,Image logo,Image qr,string output)
    {
        const string P="landscape-16x9";
        using(var bitmap=new Bitmap(3840,2160,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);Configure(g);
            Hero(g,hero,new RectangleF(1810,0,2030,755));
            Polygon(g,Color.White,new PointF(1740,0),new PointF(2610,0),new PointF(2290,360),new PointF(1810,755),new PointF(1740,755));
            Logo(g,logo,95,75,650);
            Line(g,Blue,3,825,88,825,222);
            Text(g,P,"KHỐI CƠ ĐIỆN",895,111,840,100,70,FontStyle.Bold,Navy);
            Text(g,P,"TIMELINE",90,290,1670,205,159,FontStyle.Bold,Navy);
            Text(g,P,"WORKSHOP AI",90,460,1690,218,179,FontStyle.Bold,Blue);
            Text(g,P,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",95,678,1620,70,47,FontStyle.Bold,Navy);
            Line(g,Blue,4,72,777,3768,777);
            Line(g,Rule,2,2582,816,2582,2085);
            Section(g,P,"MỞ ĐẦU","",72,818,2440,94,590,72,60);
            Line(g,Blue,5,145,920,145,1198);
            string[] openingTimes={"08:30 – 08:40","08:40 – 08:55"};
            string[] openingTitles={"VÕ THANH CANG","Minigame: Giải mã công trường AI"};
            string[] openingMeta={"Giám đốc Khối Cơ Điện chia sẻ","Quà hấp dẫn"};
            for(int i=0;i<2;i++)
            {
                float y=936+i*143;
                Node(g,145,y+38);Time(g,P,openingTimes[i],200,y,380,84,50);
                Line(g,Rule,2,620,y,620,y+111);
                Text(g,P,openingTitles[i],660,y-7,1840,85,64,FontStyle.Bold,Navy);
                Text(g,P,openingMeta[i],660,y+70,1840,69,47,FontStyle.Regular,Meta);
                if(i==0) Line(g,Rule,2,660,y+129,2512,y+129);
            }
            Section(g,P,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",72,1240,2440,94,520,72,61);
            float titleSize=Fit(g,Titles,67,48,1862,FontStyle.Bold);
            float metaSize=Fit(g,Presenters,50,38,1840,FontStyle.Italic);
            Line(g,Blue,5,145,1338,145,2075);
            for(int i=0;i<5;i++)
            {
                float y=1363+i*145;
                Node(g,145,y+40);Time(g,P,Times[i],200,y,380,84,50);
                Line(g,Rule,2,620,y-2,620,y+116);
                Text(g,P,Titles[i],650,y-6,1862,89,titleSize,FontStyle.Bold,Navy);
                Text(g,P,Presenters[i],671,y+73,1841,72,metaSize,FontStyle.Italic,Meta);
                if(i<4) Line(g,Rule,2,650,y+134,2512,y+134);
            }
            Section(g,P,"PHẦN 2","",2665,818,1103,94,600,72,60);
            Time(g,P,"10:15 – 10:50",2735,942,660,82,56);
            Text(g,P,"ỨNG DỤNG AI CÓ TRÁCH NHIỆM",2700,1051,1068,78,53,FontStyle.Bold,Navy);
            float presenterSize=Fit(g,new[]{"Trình bày: Trương Quang Vinh - Văn phòng: P.CNTT"},38,28,1068,FontStyle.Italic);
            Text(g,P,"Trình bày: Trương Quang Vinh - Văn phòng: P.CNTT",2700,1130,1068,63,presenterSize,FontStyle.Italic,Meta);
            float topicSize=Fit(g,PartTwo,45,35,1068,FontStyle.Regular);
            for(int i=0;i<4;i++) Text(g,P,PartTwo[i],2700,1215+i*76,1068,75,topicSize,FontStyle.Regular,Navy);
            Section(g,P,"PHẦN 3","",2665,1550,1103,94,600,72,60);
            Time(g,P,"10:50 – 11:00",2735,1670,660,82,56);
            Text(g,P,"TỔNG KẾT",2700,1778,1068,90,75,FontStyle.Bold,Navy);
            Qr(g,qr,3100,1850,277);
            Polygon(g,Color.FromArgb(228,242,255),new PointF(0,2115),new PointF(460,2115),new PointF(410,2160),new PointF(0,2160));
            Polygon(g,Color.FromArgb(228,242,255),new PointF(3840,1850),new PointF(3840,2160),new PointF(3510,2160));
            Polygon(g,Blue,new PointF(3840,1980),new PointF(3840,2160),new PointF(3640,2160));
            bitmap.Save(Path.Combine(output,"Newtecons-Workshop-AI-NEW-16x9-3840x2160.png"),ImageFormat.Png);
        }
    }

    public static void RenderAll(string heroPath,string logoPath,string qrPath,string output)
    {
        Audit.Clear();Directory.CreateDirectory(output);
        using(var hero=Image.FromFile(heroPath))
        using(var logo=Image.FromFile(logoPath))
        using(var qr=Image.FromFile(qrPath))
        {
            Portrait(hero,logo,qr,output);
            Landscape(hero,logo,qr,output);
        }
    }
}
