public sealed class OptionBoundsRecord
{
    public string Poster { get; set; }
    public string Text { get; set; }
    public float X { get; set; }
    public float Y { get; set; }
    public float MeasuredWidth { get; set; }
    public float LineHeight { get; set; }
    public int CanvasWidth { get; set; }
    public int CanvasHeight { get; set; }
    public bool FitsCanvas { get; set; }
}

public static partial class PosterRenderer
{
    public static readonly List<OptionBoundsRecord> OptionBounds = new List<OptionBoundsRecord>();
    static readonly Color BrandRed = Color.FromArgb(230,48,44);
    static readonly Color Signature = Color.FromArgb(8,31,61);
    static readonly Color LightMeta = Color.FromArgb(190,208,227);
    static readonly Color DarkRule = Color.FromArgb(60,81,107);
    static int OptionWidth, OptionHeight;
    static string OptionId;

    static void OText(Graphics g,string text,float x,float y,float width,float size,FontStyle style,Color color,string family="Roboto Condensed",bool center=false)
    {
        float measured=Measure(g,text,size,style,family);
        float lineHeight;
        using(var font=NewFont(size,style,family)) lineHeight=font.GetHeight(g);
        float realX=center?x+(width-measured)/2:x;
        bool fits=realX>=0&&y>=0&&realX+measured<=OptionWidth+0.1f&&y+lineHeight<=OptionHeight+0.1f;
        OptionBounds.Add(new OptionBoundsRecord{Poster=OptionId,Text=text,X=realX,Y=y,MeasuredWidth=measured,LineHeight=lineHeight,CanvasWidth=OptionWidth,CanvasHeight=OptionHeight,FitsCanvas=fits});
        if(!fits) throw new InvalidOperationException("Option text outside canvas: "+text);
        Text(g,OptionId,text,x,y,width,lineHeight,size,style,color,family,center);
    }

    static void OFitText(Graphics g,string text,float x,float y,float width,float maxSize,float minSize,FontStyle style,Color color,string family="Roboto Condensed")
    {
        float size=Fit(g,new[]{text},maxSize,minSize,width,style,family);
        OText(g,text,x,y,width,size,style,color,family);
    }

    static void OStart(Graphics g,string id,int width,int height,Color background)
    {
        Configure(g);g.Clear(background);OptionId=id;OptionWidth=width;OptionHeight=height;
    }

    static void OSection(Graphics g,string label,string sub,float x,float y,float width,bool dark,float labelSize=62,float subSize=47)
    {
        Color ink=dark?Color.White:Navy;
        Color rule=dark?DarkRule:Rule;
        Rect(g,BrandRed,x,y+10,9,54);
        OText(g,label,x+30,y,width-30,labelSize,FontStyle.Bold,ink,"Arial");
        if(!string.IsNullOrEmpty(sub))
        {
            float sx=x+375;
            OFitText(g,sub,sx,y+12,width-375,subSize,32,FontStyle.Bold,dark?LightMeta:Meta);
        }
        Line(g,rule,2,x,y+83,x+width,y+83);
    }

    static void OBigTitle(Graphics g,float x,float y,float width,float maxSize,float minSize,Color workshop,Color ai)
    {
        const string family="Arial";
        float size=maxSize,ww=0,aw=0;
        while(size>=minSize)
        {
            ww=Measure(g,"WORKSHOP",size,FontStyle.Bold,family);
            aw=Measure(g,"AI",size,FontStyle.Bold,family);
            if(ww+aw+58<=width) break;
            size-=0.5f;
        }
        if(size<minSize) throw new InvalidOperationException("Cannot fit option main headline");
        OText(g,"WORKSHOP",x,y,ww+2,size,FontStyle.Bold,workshop,family);
        OText(g,"AI",x+ww+58,y,aw+2,size,FontStyle.Bold,ai,family);
    }

    static void OBrand(Graphics g,Image logo,float x,float y,float logoWidth,float separatorX,float textX,float textWidth,bool plaque)
    {
        if(plaque) Rect(g,Color.White,x-38,y-25,OptionWidth-2*(x-38),205);
        Logo(g,logo,x,y,logoWidth);
        Line(g,BrandRed,3,separatorX,y+16,separatorX,y+135);
        OText(g,"KHỐI CƠ ĐIỆN",textX,y+38,textWidth,65,FontStyle.Bold,Navy,"Arial");
    }

    static void ODate(Graphics g,float x,float y,float width,float height,float size)
    {
        Rect(g,BrandRed,x,y,width,height);
        OText(g,"14.11.2026",x+20,y+13,width-40,size,FontStyle.Bold,Color.White,"Arial",true);
    }

    static void OOpening(Graphics g,float x,float y,float width,float step,bool dark,bool timeRight,float titleSize,float metaSize,float timeSize,float timeWidth)
    {
        string[] times={"08:30 – 08:40","08:40 – 08:55"};
        string[] names={"VÕ THANH CANG","Minigame: Giải mã công trường AI"};
        string[] metadata={"Giám đốc Khối Cơ Điện chia sẻ","Quà hấp dẫn"};
        Color ink=dark?Color.White:Navy,meta=dark?LightMeta:Meta;
        float topicX=timeRight?x:x+timeWidth+50;
        float topicWidth=width-timeWidth-65;
        float timeX=timeRight?x+width-timeWidth:x;
        for(int i=0;i<2;i++)
        {
            float ry=y+i*step;
            OText(g,times[i],timeX,ry+5,timeWidth,timeSize,FontStyle.Bold,dark?Color.White:Meta);
            OFitText(g,names[i],topicX,ry,topicWidth,titleSize,titleSize-10,FontStyle.Bold,ink);
            OFitText(g,metadata[i],topicX,ry+67,topicWidth,metaSize,metaSize-6,FontStyle.Regular,meta);
            if(i==0) Line(g,dark?DarkRule:Rule,1.6f,topicX,ry+step-3,x+width,ry+step-3);
        }
    }

    static void OTalks(Graphics g,float x,float y,float width,float step,bool dark,bool timeRight,float maxTitle,float maxMeta,float timeSize,float timeWidth)
    {
        Color ink=dark?Color.White:Navy,meta=dark?LightMeta:Meta;
        float textX=timeRight?x:x+timeWidth+50;
        float textWidth=width-timeWidth-65;
        float timeX=timeRight?x+width-timeWidth:x;
        float titleSize=Fit(g,Titles,maxTitle,maxTitle-15,textWidth,FontStyle.Bold);
        float metaSize=Fit(g,Presenters,maxMeta,maxMeta-10,textWidth-5,FontStyle.Italic);
        for(int i=0;i<5;i++)
        {
            float ry=y+i*step;
            OText(g,Times[i],timeX,ry+7,timeWidth,timeSize,FontStyle.Bold,dark?Color.White:Meta);
            OText(g,Titles[i],textX,ry,textWidth,titleSize,FontStyle.Bold,ink);
            OText(g,Presenters[i],textX+4,ry+70,textWidth-5,metaSize,FontStyle.Italic,meta);
            if(i<4) Line(g,dark?DarkRule:Rule,1.5f,textX,ry+step-14,x+width,ry+step-14);
        }
    }

    static void OPartTwo(Graphics g,float x,float y,float width,bool dark,float headingSize,float speakerSize,float topicSize,float topicStep)
    {
        Color ink=dark?Color.White:Navy,meta=dark?LightMeta:Meta;
        OFitText(g,"ỨNG DỤNG AI CÓ TRÁCH NHIỆM",x,y,width,headingSize,headingSize-12,FontStyle.Bold,ink);
        OFitText(g,"Trình bày: Trương Quang Vinh - Văn phòng: P.CNTT",x,y+82,width,speakerSize,speakerSize-10,FontStyle.Italic,meta);
        float fitted=Fit(g,PartTwo,topicSize,topicSize-10,width,FontStyle.Regular);
        for(int i=0;i<4;i++) OText(g,PartTwo[i],x+4,y+167+i*topicStep,width-4,fitted,FontStyle.Regular,ink);
    }

    static void EditorialPortrait(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(2160,3840,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);OStart(g,"option-01-editorial-9x16",2160,3840,Color.White);
            OBrand(g,logo,72,65,620,790,855,1230,false);
            OText(g,"TIMELINE",74,260,1200,50,FontStyle.Bold,Meta,"Arial");
            ODate(g,1610,252,478,82,47);
            OBigTitle(g,72,350,2016,210,160,Navy,BrandRed);
            OText(g,"12A NEWTECONS   |   08:30 – 11:00",78,584,2010,51,FontStyle.Bold,Navy,"Arial");
            Hero(g,hero,new RectangleF(72,680,2016,752));
            Rect(g,BrandRed,72,1432,128,12);
            OSection(g,"MỞ ĐẦU","",72,1480,2016,false);
            OOpening(g,90,1587,1998,120,false,false,57,43,44,350);
            OSection(g,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",72,1865,2016,false,62,44);
            OTalks(g,90,1978,1998,136,false,false,57,43,44,350);
            OSection(g,"PHẦN 2","10:15 – 10:50",72,2700,2016,false);
            OPartTwo(g,100,2805,1988,false,65,46,47,60);
            OSection(g,"PHẦN 3","10:50 – 11:00",72,3290,2016,false);
            OText(g,"TỔNG KẾT",100,3398,1988,76,FontStyle.Bold,Navy,"Arial");
            Qr(g,qr,930,3485,300);
            Line(g,BrandRed,8,72,3807,2088,3807);
            bitmap.Save(Path.Combine(output,"Option-01-Editorial-9x16-4K.png"),ImageFormat.Png);
        }
    }

    static void EditorialLandscape(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(3840,2160,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);OStart(g,"option-01-editorial-16x9",3840,2160,Color.White);
            OBrand(g,logo,72,62,620,790,850,1000,false);
            OText(g,"TIMELINE",76,280,1700,50,FontStyle.Bold,Meta,"Arial");
            OBigTitle(g,72,365,1710,185,145,Navy,BrandRed);
            ODate(g,72,613,416,90,44);
            OFitText(g,"12A NEWTECONS   |   08:30 – 11:00",530,640,1300,47,40,FontStyle.Bold,Navy);
            Hero(g,hero,new RectangleF(1950,0,1890,704));
            Rect(g,BrandRed,1950,704,128,12);
            OSection(g,"MỞ ĐẦU","",72,792,2460,false);
            OOpening(g,90,903,2442,143,false,false,64,47,50,435);
            OSection(g,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",72,1230,2460,false,62,58);
            OTalks(g,90,1350,2442,145,false,false,67,50,50,435);
            Line(g,Rule,2,2600,790,2600,2098);
            OSection(g,"PHẦN 2","",2675,792,1093,false);
            OText(g,"10:15 – 10:50",2700,904,1068,55,FontStyle.Bold,Meta);
            OPartTwo(g,2700,1010,1068,false,54,36,43,77);
            OSection(g,"PHẦN 3","",2675,1545,1093,false);
            OText(g,"10:50 – 11:00",2700,1655,1068,55,FontStyle.Bold,Meta);
            OText(g,"TỔNG KẾT",2700,1745,1068,72,FontStyle.Bold,Navy,"Arial");
            Qr(g,qr,3200,1810,285);
            Line(g,BrandRed,8,72,2120,3768,2120);
            bitmap.Save(Path.Combine(output,"Option-01-Editorial-16x9-4K.png"),ImageFormat.Png);
        }
    }

    static void SignaturePortrait(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(2160,3840,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);OStart(g,"option-02-signature-9x16",2160,3840,Signature);
            Rect(g,Color.White,72,65,2016,205);
            OBrand(g,logo,110,90,635,825,900,1150,false);
            OText(g,"TIMELINE",92,330,1900,47,FontStyle.Bold,LightMeta,"Arial");
            OBigTitle(g,82,405,1996,203,160,Color.White,BrandRed);
            OText(g,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",90,635,1980,49,FontStyle.Bold,Color.White);
            Hero(g,hero,new RectangleF(72,735,2016,690));
            Rect(g,BrandRed,72,1425,2016,10);
            OSection(g,"MỞ ĐẦU","",72,1480,2016,true);
            OOpening(g,95,1587,1940,120,true,true,57,43,43,330);
            OSection(g,"PHẦN 1","ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",72,1865,2016,true,62,44);
            OTalks(g,95,1978,1940,136,true,true,57,43,43,330);
            OSection(g,"PHẦN 2","10:15 – 10:50",72,2700,2016,true);
            OPartTwo(g,100,2805,1988,true,65,46,47,60);
            OSection(g,"PHẦN 3","10:50 – 11:00",72,3290,2016,true);
            OText(g,"TỔNG KẾT",100,3398,1988,76,FontStyle.Bold,Color.White,"Arial");
            Qr(g,qr,920,3485,320);
            bitmap.Save(Path.Combine(output,"Option-02-Signature-Navy-9x16-4K.png"),ImageFormat.Png);
        }
    }

    static void SignatureLandscape(Image hero,Image logo,Image qr,string output)
    {
        using(var bitmap=new Bitmap(3840,2160,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(bitmap))
        {
            bitmap.SetResolution(300,300);OStart(g,"option-02-signature-16x9",3840,2160,Signature);
            Rect(g,Color.White,0,0,3840,200);
            OBrand(g,logo,72,23,620,790,850,1800,false);
            Hero(g,hero,new RectangleF(72,250,1400,520));
            OText(g,"TIMELINE",1565,272,2185,47,FontStyle.Bold,LightMeta,"Arial");
            OBigTitle(g,1555,355,2200,217,165,Color.White,BrandRed);
            OText(g,"14.11.2026   |   12A NEWTECONS   |   08:30 – 11:00",1565,617,2190,51,FontStyle.Bold,Color.White);
            Rect(g,BrandRed,1565,737,2185,10);
            OSection(g,"MỞ ĐẦU","",72,842,770,true,60,42);
            OText(g,"08:30 – 08:40",95,974,700,53,FontStyle.Bold,Color.White);
            OText(g,"VÕ THANH CANG",95,1068,700,64,FontStyle.Bold,Color.White);
            OFitText(g,"Giám đốc Khối Cơ Điện chia sẻ",95,1152,700,44,35,FontStyle.Regular,LightMeta);
            Line(g,DarkRule,2,95,1270,820,1270);
            OText(g,"08:40 – 08:55",95,1330,700,53,FontStyle.Bold,Color.White);
            OText(g,"Minigame:",95,1428,700,61,FontStyle.Bold,Color.White);
            OText(g,"Giải mã công trường AI",95,1505,700,53,FontStyle.Bold,Color.White);
            OText(g,"Quà hấp dẫn",95,1590,700,45,FontStyle.Regular,LightMeta);
            Line(g,DarkRule,2,880,842,880,2090);
            OSection(g,"PHẦN 1","",940,842,1830,true,60,42);
            OFitText(g,"ỨNG DỤNG AI THỰC TẾ Ở CÔNG TRƯỜNG",965,949,1780,45,38,FontStyle.Bold,LightMeta);
            OTalks(g,965,1060,1785,196,true,true,56,41,41,322);
            Line(g,DarkRule,2,2825,842,2825,2090);
            OSection(g,"PHẦN 2","",2890,842,878,true,60,42);
            OText(g,"10:15 – 10:50",2915,961,830,48,FontStyle.Bold,Color.White);
            OPartTwo(g,2915,1052,830,true,43,31,36,77);
            OSection(g,"PHẦN 3","",2890,1560,878,true,60,42);
            OText(g,"10:50 – 11:00",2915,1671,830,48,FontStyle.Bold,Color.White);
            OText(g,"TỔNG KẾT",2915,1764,830,66,FontStyle.Bold,Color.White,"Arial");
            Qr(g,qr,3185,1874,260);
            bitmap.Save(Path.Combine(output,"Option-02-Signature-Navy-16x9-4K.png"),ImageFormat.Png);
        }
    }

    static void OptionContactSheet(string output)
    {
        using(var sheet=new Bitmap(2400,1800,PixelFormat.Format24bppRgb))
        using(var g=Graphics.FromImage(sheet))
        {
            Configure(g);g.Clear(Color.FromArgb(232,237,243));
            string[] names={"Option-01-Editorial-9x16-4K.png","Option-01-Editorial-16x9-4K.png","Option-02-Signature-Navy-9x16-4K.png","Option-02-Signature-Navy-16x9-4K.png"};
            using(var img=Image.FromFile(Path.Combine(output,names[0]))) g.DrawImage(img,new RectangleF(315,55,540,960));
            using(var img=Image.FromFile(Path.Combine(output,names[1]))) g.DrawImage(img,new RectangleF(25,1100,1150,646.875f));
            using(var img=Image.FromFile(Path.Combine(output,names[2]))) g.DrawImage(img,new RectangleF(1515,55,540,960));
            using(var img=Image.FromFile(Path.Combine(output,names[3]))) g.DrawImage(img,new RectangleF(1225,1100,1150,646.875f));
            using(var font=new Font("Arial",20,FontStyle.Bold,GraphicsUnit.Pixel))
            using(var brush=new SolidBrush(Navy))
            {
                g.DrawString("01 / EDITORIAL",font,brush,315,18);
                g.DrawString("01 / EDITORIAL",font,brush,25,1062);
                g.DrawString("02 / SIGNATURE NAVY",font,brush,1515,18);
                g.DrawString("02 / SIGNATURE NAVY",font,brush,1225,1062);
            }
            sheet.Save(Path.Combine(output,"Options-Contact-Sheet.png"),ImageFormat.Png);
        }
    }

    public static void RenderOptions(string heroAPath,string heroBPath,string logoPath,string qrPath,string output)
    {
        Audit.Clear();OptionBounds.Clear();Directory.CreateDirectory(output);
        using(var heroA=Image.FromFile(heroAPath))
        using(var heroB=Image.FromFile(heroBPath))
        using(var logo=Image.FromFile(logoPath))
        using(var qr=Image.FromFile(qrPath))
        {
            EditorialPortrait(heroA,logo,qr,output);
            EditorialLandscape(heroA,logo,qr,output);
            SignaturePortrait(heroB,logo,qr,output);
            SignatureLandscape(heroB,logo,qr,output);
        }
        OptionContactSheet(output);
    }
}
