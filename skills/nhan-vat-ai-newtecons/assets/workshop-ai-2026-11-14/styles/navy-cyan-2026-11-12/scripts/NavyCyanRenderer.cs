using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;

public sealed class NavyCyanBoundsRecord
{
    public string Poster { get; set; }
    public string Text { get; set; }
    public float X { get; set; }
    public float Y { get; set; }
    public float Width { get; set; }
    public float Height { get; set; }
    public float MeasuredHeight { get; set; }
    public int CanvasWidth { get; set; }
    public int CanvasHeight { get; set; }
    public bool FitsCanvas { get; set; }
}

public sealed class NavyCyanImageRecord
{
    public string Poster { get; set; }
    public int SourceWidth { get; set; }
    public int SourceHeight { get; set; }
    public float X { get; set; }
    public float Y { get; set; }
    public float Width { get; set; }
    public float Height { get; set; }
    public float Scale { get; set; }
    public bool Upscaled { get; set; }
}

// Extends the approved renderer so the five titles, presenters, times, topics,
// logo and QR drawing routines retain their original source of truth.
public static partial class PosterRenderer
{
    public static readonly List<NavyCyanBoundsRecord> NavyCyanBounds = new List<NavyCyanBoundsRecord>();
    public static readonly List<NavyCyanImageRecord> NavyCyanImages = new List<NavyCyanImageRecord>();
    static readonly Color NCBg = Color.FromArgb(4,30,53);
    static readonly Color NCDeep = Color.FromArgb(6,24,45);
    static readonly Color NCCyan = Color.FromArgb(0,220,250);
    static readonly Color NCSecondary = Color.FromArgb(209,228,241);
    static readonly Color NCRule = Color.FromArgb(35,104,130);
    static int NCWidth, NCHeight;
    static string NCId;

    static void NCStart(Graphics g,string id,int w,int h)
    {
        Configure(g);NCId=id;NCWidth=w;NCHeight=h;
        using(var brush=new LinearGradientBrush(new Rectangle(0,0,w,h),NCBg,NCDeep,90f)) g.FillRectangle(brush,0,0,w,h);
    }
    static void NCText(Graphics g,string text,float x,float y,float width,float size,FontStyle style,Color color,bool center=false)
    {
        float measured=Measure(g,text,size,style);
        float height;
        using(var font=NewFont(size,style)) height=font.GetHeight(g);
        float realX=center?x+(width-measured)/2:x;
        bool fits=realX>=0&&y>=0&&realX+measured<=NCWidth+0.1f&&y+height<=NCHeight+0.1f;
        NavyCyanBounds.Add(new NavyCyanBoundsRecord{Poster=NCId,Text=text,X=realX,Y=y,Width=measured,Height=height,MeasuredHeight=height,CanvasWidth=NCWidth,CanvasHeight=NCHeight,FitsCanvas=fits});
        if(!fits) throw new InvalidOperationException("Navy cyan text outside canvas: "+text);
        Text(g,NCId,text,x,y,width,height,size,style,color,"Roboto Condensed",center);
    }
    static void NCFitText(Graphics g,string text,float x,float y,float width,float maxSize,float minSize,FontStyle style,Color color)
    {
        NCText(g,text,x,y,width,Fit(g,new[]{text},maxSize,minSize,width,style),style,color);
    }
    static GraphicsPath NCRounded(float x,float y,float w,float h,float radius)
    {
        var p=new GraphicsPath();float d=radius*2;
        p.AddArc(x,y,d,d,180,90);p.AddArc(x+w-d,y,d,d,270,90);
        p.AddArc(x+w-d,y+h-d,d,d,0,90);p.AddArc(x,y+h-d,d,d,90,90);p.CloseFigure();return p;
    }
    static void NCPanel(Graphics g,float x,float y,float w,float h)
    {
        using(var path=NCRounded(x,y,w,h,25))
        using(var b=new SolidBrush(Color.FromArgb(190,6,24,45)))
        using(var p=new Pen(Color.FromArgb(150,0,220,250),3)) {g.FillPath(b,path);g.DrawPath(p,path);}
    }
    static void NCSection(Graphics g,string label,string sub,float x,float y,float width,float labelWidth,float labelSize,float subSize)
    {
        Rect(g,Color.FromArgb(20,64,91),x,y,width,100);
        Polygon(g,NCCyan,new PointF(x+27,y),new PointF(x+labelWidth,y),new PointF(x+labelWidth-50,y+100),new PointF(x,y+100));
        Polygon(g,Color.FromArgb(65,154,197),new PointF(x+labelWidth+15,y),new PointF(x+labelWidth+32,y),new PointF(x+labelWidth-18,y+100),new PointF(x+labelWidth-35,y+100));
        NCText(g,label,x+38,y+7,labelWidth-80,labelSize,FontStyle.Bold,NCDeep);
        if(!string.IsNullOrEmpty(sub)) NCFitText(g,sub,x+labelWidth+53,y+17,width-labelWidth-70,subSize,34,FontStyle.Bold,Color.White);
    }
    static void NCTime(Graphics g,string text,float x,float y,float w,float h,float size)
    {
        using(var path=NCRounded(x,y,w,h,h/2))
        using(var brush=new SolidBrush(NCCyan)) g.FillPath(brush,path);
        NCText(g,text,x+14,y+5,w-28,size,FontStyle.Bold,NCDeep,true);
    }
    static void NCNode(Graphics g,float x,float y)
    {
        using(var brush=new SolidBrush(NCDeep)) g.FillEllipse(brush,x-14,y-14,28,28);
        using(var pen=new Pen(NCCyan,5)) g.DrawEllipse(pen,x-14,y-14,28,28);
    }
    static void NCBrand(Graphics g,Image logo,float x,float y,float w,float h)
    {
        Polygon(g,Color.White,new PointF(x+30,y),new PointF(x+w,y),new PointF(x+w-62,y+h),new PointF(x,y+h));
        float logoW=w*.47f;
        Logo(g,logo,x+70,y+(h-logoW*logo.Height/logo.Width)/2,logoW);
        float divider=x+w*.56f;
        Line(g,Blue,3,divider,y+30,divider,y+h-30);
        NCFitText(g,"KHỐI CƠ ĐIỆN",divider+45,y+h*.29f,w*.38f-80,h*.38f,42,FontStyle.Bold,NCDeep);
    }
    static void NCHeadline(Graphics g,float x,float y,float width,float maxSize,bool center=false)
    {
        float size=maxSize;
        while(Measure(g,"WORKSHOP",size,FontStyle.Bold)+Measure(g,"AI",size,FontStyle.Bold)+45>width) size-=.5f;
        float workshopW=Measure(g,"WORKSHOP",size,FontStyle.Bold);
        float total=workshopW+Measure(g,"AI",size,FontStyle.Bold)+45;
        if(center) x+=(width-total)/2;
        float aiX=x+workshopW+45;
        // Restrained cyan glow belongs only to AI; actual letters remain native text.
        using(var path=new GraphicsPath())
        using(var family=new FontFamily("Roboto Condensed"))
        {
            path.AddString("AI",family,(int)FontStyle.Bold,size,new PointF(aiX,y),StringFormat.GenericTypographic);
            for(int i=12;i>=3;i-=3) using(var pen=new Pen(Color.FromArgb(12,NCCyan),i)) g.DrawPath(pen,path);
        }
        NCText(g,"WORKSHOP",x,y,workshopW+2,size,FontStyle.Bold,Color.White);
        NCText(g,"AI",aiX,y,width-(aiX-x),size,FontStyle.Bold,NCCyan);
    }
    static void NCHeaderPhoto(Graphics g,Image hero,RectangleF box,bool fadeLeft)
    {
        float scale=Math.Max(box.Width/hero.Width,box.Height/hero.Height);
        if(scale>1.00001f) throw new InvalidOperationException("Generated hero must not be enlarged. Scale="+scale);
        NavyCyanImages.Add(new NavyCyanImageRecord{Poster=NCId,SourceWidth=hero.Width,SourceHeight=hero.Height,X=box.X,Y=box.Y,Width=box.Width,Height=box.Height,Scale=scale,Upscaled=scale>1.00001f});
        Hero(g,hero,box);
        if(fadeLeft)
        {
            using(var b=new LinearGradientBrush(new RectangleF(box.X,box.Y,box.Width*.38f,box.Height),NCBg,Color.FromArgb(0,NCBg),0f))
                g.FillRectangle(b,box.X,box.Y,box.Width*.38f,box.Height);
        }
        using(var b=new LinearGradientBrush(new RectangleF(box.X,box.Bottom-140,box.Width,140),Color.FromArgb(0,NCBg),NCBg,90f))
            g.FillRectangle(b,box.X,box.Bottom-140,box.Width,140);
    }
    static void NCAgenda(Graphics g,float x,float y,float w,float step,float timeW,float titleMax,float presenterMax)
    {
        float tx=x+timeW+89,tw=w-(tx-x);
        float titleSize=Fit(g,Titles,titleMax,40,tw,FontStyle.Bold);
        float metaSize=Fit(g,Presenters,presenterMax,30,tw-21,FontStyle.Italic);
        Line(g,NCCyan,4,x-35,y+38,x-35,y+4*step+38);
        for(int i=0;i<5;i++)
        {
            float ry=y+i*step;
            NCNode(g,x-35,ry+38);NCTime(g,Times[i],x,ry,timeW,80,48);
            Line(g,NCRule,2,tx-30,ry,tx-30,ry+120);
            NCText(g,Titles[i],tx,ry-5,tw,titleSize,FontStyle.Bold,Color.White);
            NCText(g,Presenters[i],tx+21,ry+75,tw-21,metaSize,FontStyle.Italic,NCSecondary);
            if(i<4) Line(g,NCRule,2,tx,ry+step-18,x+w,ry+step-18);
        }
    }
    static void NCPartTwo(Graphics g,float x,float y,float w,bool portrait)
    {
        float heading=portrait?67:53,meta=portrait?48:38,topic=portrait?49:45;
        NCText(g,"ỨNG DỤNG AI CÓ TRÁCH NHIỆM",x,y,w,heading,FontStyle.Bold,Color.White);
        NCFitText(g,"Trình bày: Trương Quang Vinh - Văn phòng: P.CNTT",x,y+80,w,meta,28,FontStyle.Italic,NCSecondary);
        float topicSize=Fit(g,PartTwo,topic,32,w,FontStyle.Regular);
        for(int i=0;i<4;i++) NCText(g,PartTwo[i],x,y+(portrait?155:165)+i*(portrait?60:66),w,topicSize,FontStyle.Regular,Color.White);
    }
    static void NCFooter(Graphics g)
    {
        Polygon(g,Color.FromArgb(20,73,111),new PointF(NCWidth-650,NCHeight),new PointF(NCWidth-500,NCHeight-75),new PointF(NCWidth,NCHeight-75),new PointF(NCWidth,NCHeight));
        Line(g,NCCyan,3,NCWidth-420,NCHeight-20,NCWidth-30,NCHeight-20);
    }
    static void NCLandscape(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(3840,2160,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);NCStart(g,"navy-cyan-landscape-16x9",3840,2160);
            NCHeaderPhoto(g,hero,new RectangleF(1668,0,2172,724),true);
            NCBrand(g,logo,50,42,1560,180);
            NCHeadline(g,75,285,1640,180);
            NCText(g,"TIMELINE CHƯƠNG TRÌNH",85,500,1630,78,FontStyle.Bold,Color.White);
            Line(g,NCCyan,3,80,610,1640,610);
            NCText(g,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",85,652,1650,49,FontStyle.Bold,Color.White);
            NCPanel(g,55,790,3730,230);
            NCSection(g,"MỞ ĐẦU","",80,815,510,490,68,50);
            Line(g,NCRule,2,635,825,635,985);
            NCTime(g,"08:30 – 08:40",690,835,390,80,49);
            NCText(g,"VÕ THANH CANG",1120,828,760,64,FontStyle.Bold,Color.White);
            NCText(g,"Giám đốc Khối Cơ Điện chia sẻ",1120,910,760,47,FontStyle.Regular,NCSecondary);
            Line(g,NCRule,2,1950,825,1950,985);
            NCTime(g,"08:40 – 08:55",2010,835,390,80,49);
            NCText(g,"Minigame: Giải mã công trường AI",2440,828,1260,64,FontStyle.Bold,Color.White);
            NCText(g,"Quà hấp dẫn",2440,910,1260,47,FontStyle.Regular,NCSecondary);
            NCPanel(g,55,1050,2500,1025);
            NCSection(g,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",80,1075,2450,520,72,61);
            NCAgenda(g,130,1210,2390,166,380,67,50);
            NCPanel(g,2600,1050,1185,580);
            NCSection(g,"PHẦN 2","10:15 – 10:50",2625,1075,1135,445,72,53);
            NCPartTwo(g,2640,1197,1100,false);
            NCPanel(g,2600,1660,1185,415);
            NCSection(g,"PHẦN 3","10:50 – 11:00",2625,1685,1135,445,72,53);
            NCText(g,"TỔNG KẾT",2640,1800,1100,69,FontStyle.Bold,Color.White);
            Qr(g,qr,3035,1805,250);
            NCFooter(g);
            bitmap.Save(Path.Combine(output,"Newtecons-Workshop-AI-Navy-Cyan-16x9-4K.png"),ImageFormat.Png);
        }
    }
    static void NCPortrait(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(2160,3840,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);NCStart(g,"navy-cyan-portrait-9x16",2160,3840);
            NCHeaderPhoto(g,hero,new RectangleF(0,220,2160,720),false);
            NCBrand(g,logo,50,40,1580,180);
            NCHeadline(g,150,945,1860,185,true);
            NCText(g,"TIMELINE CHƯƠNG TRÌNH",120,1167,1920,75,FontStyle.Bold,Color.White,true);
            NCText(g,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",90,1270,1980,55,FontStyle.Bold,Color.White,true);
            NCPanel(g,60,1350,2040,400);
            NCSection(g,"MỞ ĐẦU","",85,1375,1990,550,72,60);
            Line(g,NCCyan,4,140,1517,140,1643);
            string[] openingTimes={"08:30 – 08:40","08:40 – 08:55"};
            string[] openingTitles={"VÕ THANH CANG","Minigame: Giải mã công trường AI"};
            string[] openingMeta={"Giám đốc Khối Cơ Điện chia sẻ","Quà hấp dẫn"};
            for(int i=0;i<2;i++)
            {
                float y=1485+i*125;
                NCNode(g,140,y+38);NCTime(g,openingTimes[i],188,y,370,80,48);
                NCText(g,openingTitles[i],640,y-5,1410,58,FontStyle.Bold,Color.White);
                NCText(g,openingMeta[i],640,y+68,1410,44,FontStyle.Regular,NCSecondary);
            }
            NCPanel(g,60,1790,2040,900);
            NCSection(g,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",85,1815,1990,485,72,55);
            NCAgenda(g,188,1940,1867,145,370,58,44);
            NCPanel(g,60,2725,2040,550);
            NCSection(g,"PHẦN 2","10:15 – 10:50",85,2750,1990,485,72,61);
            NCPartTwo(g,140,2860,1900,true);
            NCPanel(g,60,3310,2040,470);
            NCSection(g,"PHẦN 3","10:50 – 11:00",85,3335,1990,485,72,61);
            NCText(g,"TỔNG KẾT",140,3445,1900,68,FontStyle.Bold,Color.White);
            Qr(g,qr,970,3530,220);
            NCFooter(g);
            bitmap.Save(Path.Combine(output,"Newtecons-Workshop-AI-Navy-Cyan-9x16-4K.png"),ImageFormat.Png);
        }
    }
    public static void RenderNavyCyan(string heroPath,string logoPath,string qrPath,string output)
    {
        Audit.Clear();NavyCyanBounds.Clear();NavyCyanImages.Clear();Directory.CreateDirectory(output);
        using(var hero=Image.FromFile(heroPath))
        using(var logo=Image.FromFile(logoPath))
        using(var qr=Image.FromFile(qrPath))
        {NCPortrait(hero,logo,qr,output);NCLandscape(hero,logo,qr,output);}
    }
}
